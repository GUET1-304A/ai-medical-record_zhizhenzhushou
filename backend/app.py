# app.py - 最终回归版 (使用讯飞API进行语音转文字)

import os
import json
import sqlite3
import hashlib
import time
import re
import requests # 只使用基础的requests库
import websocket
import base64
import hmac
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread
from dotenv import load_dotenv
from functools import wraps
from flask import Flask, request, jsonify, g, session
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect

# 加载环境变量
load_dotenv()

# 讯飞API认证信息
APPID = os.getenv('APPID')
APIKey = os.getenv('APIKey')
APISecret = os.getenv('APISecret')

# 状态常量
STATUS_FIRST_FRAME = 0  # 第一帧的标识
STATUS_CONTINUE_FRAME = 1  # 中间帧标识
STATUS_LAST_FRAME = 2  # 最后一帧的标识

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_SECRET_KEY'] = 'your-csrf-secret-key-here'

# 配置CORS
CORS(app, supports_credentials=True)

# 初始化CSRF保护
csrf = CSRFProtect(app)

# 请求频率限制
rate_limit = {}
RATE_LIMIT = 5  # 每分钟最多5次请求
RATE_LIMIT_WINDOW = 60  # 60秒窗口


UPLOAD_FOLDER = 'temp_audio_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BASE_ASR_MODEL_NAME = 'conformer_wenetspeech'

# 数据库初始化
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# 获取数据库连接
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('users.db')
        g.db.row_factory = sqlite3.Row
    return g.db

# 关闭数据库连接
@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# 密码加密
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# 生成JWT令牌
def generate_token(user_id, username):
    # 简单的JWT实现，实际项目中应使用专门的JWT库
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': int(time.time()) + 3600 * 24  # 24小时过期
    }
    # 使用SHA256生成签名
    signature = hashlib.sha256((json.dumps(payload) + app.config['SECRET_KEY']).encode()).hexdigest()
    return f"{json.dumps(payload)}.{signature}"

# 请求频率限制装饰器
def rate_limit_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        client_ip = request.remote_addr
        current_time = time.time()
        
        if client_ip not in rate_limit:
            rate_limit[client_ip] = []
        
        # 清理过期的请求记录
        rate_limit[client_ip] = [t for t in rate_limit[client_ip] if current_time - t < RATE_LIMIT_WINDOW]
        
        # 检查是否超过限制
        if len(rate_limit[client_ip]) >= RATE_LIMIT:
            return jsonify({"success": False, "message": "请求过于频繁，请稍后再试"}), 429
        
        # 记录本次请求
        rate_limit[client_ip].append(current_time)
        
        return func(*args, **kwargs)
    return wrapper

# 验证JWT令牌
def verify_token(token):
    try:
        payload_str, signature = token.split('.')
        payload = json.loads(payload_str)
        expected_signature = hashlib.sha256((payload_str + app.config['SECRET_KEY']).encode()).hexdigest()
        if signature != expected_signature:
            return None
        if payload['exp'] < int(time.time()):
            return None
        return payload
    except:
        return None

# 讯飞API相关类和函数
class Ws_Param(object):
    # 初始化
    def __init__(self, APPID, APIKey, APISecret, AudioFile):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.AudioFile = AudioFile

        # 公共参数(common)
        self.CommonArgs = {"app_id": self.APPID}
        # 业务参数(business)，更多个性化参数可在官网查看
        self.BusinessArgs = {
            "domain": "iat", 
            "language": "zh_cn", 
            "accent": "mandarin", 
            "vinfo": 1, 
            "vad_eos": 10000,
            "ptt": 1  # 开启标点符号添加
        }

    # 生成url
    def create_url(self):
        url = 'wss://ws-api.xfyun.cn/v2/iat'
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/iat " + "HTTP/1.1"
        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(self.APISecret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = "api_key=\"%s\", algorithm=\"%s\", headers=\"%s\", signature=\"%s\"" % (
            self.APIKey, "hmac-sha256", "host date request-line", signature_sha)
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        # 拼接鉴权参数，生成url
        url = url + '?' + urlencode(v)
        return url

# 全局变量用于存储识别结果
recognition_result = ""
recognition_error = None

# 收到websocket消息的处理
def on_message(ws, message):
    global recognition_result, recognition_error
    try:
        code = json.loads(message)["code"]
        sid = json.loads(message)["sid"]
        if code != 0:
            errMsg = json.loads(message)["message"]
            print("sid:%s call error:%s code is:%s" % (sid, errMsg, code))
            recognition_error = "sid:%s call error:%s code is:%s" % (sid, errMsg, code)

        else:
            data = json.loads(message)["data"]["result"]["ws"]
            result = ""
            for i in data:
                for w in i["cw"]:
                    result += w["w"]
            recognition_result += result
            print("sid:%s call success!,data is:%s" % (sid, json.dumps(data, ensure_ascii=False)))
    except Exception as e:
        print("receive msg,but parse exception:", e)
        recognition_error = str(e)

# 收到websocket错误的处理
def on_error(ws, error):
    global recognition_error
    print("### error:", error)
    recognition_error = str(error)

# 收到websocket关闭的处理
def on_close(ws,a,b):
    print("### closed ###")

# 收到websocket连接建立的处理
def on_open(ws):
    def run(*args):
        frameSize = 8000  # 每一帧的音频大小
        intervel = 0.04  # 发送音频间隔(单位:s)
        status = STATUS_FIRST_FRAME  # 音频的状态信息，标识音频是第一帧，还是中间帧、最后一帧

        audio_file_path = wsParam.AudioFile
        with open(audio_file_path, "rb") as fp:
            while True:
                buf = fp.read(frameSize)
                # 文件结束
                if not buf:
                    status = STATUS_LAST_FRAME
                # 第一帧处理
                # 发送第一帧音频，带business 参数
                # appid 必须带上，只需第一帧发送
                if status == STATUS_FIRST_FRAME:
                    # 根据文件扩展名选择编码格式
                    encoding = "lame"  # 默认使用lame编码
                    audio_format = "audio/L16;rate=16000"
                    
                    # 对于MP3文件，使用lame编码
                    if audio_file_path.lower().endswith('.mp3'):
                        encoding = "lame"
                    # 对于其他格式，使用raw编码
                    else:
                        encoding = "raw"

                    d = {"common": wsParam.CommonArgs,
                         "business": wsParam.BusinessArgs,
                         "data": {"status": 0, "format": audio_format,
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": encoding}}
                    d = json.dumps(d)
                    ws.send(d)
                    status = STATUS_CONTINUE_FRAME
                # 中间帧处理
                elif status == STATUS_CONTINUE_FRAME:
                    # 使用与第一帧相同的编码格式
                    encoding = "lame" if audio_file_path.lower().endswith('.mp3') else "raw"
                    
                    d = {"data": {"status": 1, "format": "audio/L16;rate=16000",
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": encoding}}
                    ws.send(json.dumps(d))
                # 最后一帧处理
                elif status == STATUS_LAST_FRAME:
                    # 使用与第一帧相同的编码格式
                    encoding = "lame" if audio_file_path.lower().endswith('.mp3') else "raw"
                    
                    d = {"data": {"status": 2, "format": "audio/L16;rate=16000",
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": encoding}}
                    ws.send(json.dumps(d))
                    time.sleep(1)
                    break
                # 模拟音频采样间隔
                time.sleep(intervel)
        ws.close()

    thread.start_new_thread(run, ())

# 全局变量
wsParam = None


# ==================== 手动获取 Access Token 的函数 (最稳定的方式) ====================
def get_access_token():
    payload = {
        "grant_type": "client_credentials",
        "client_id": IAM_AK,
        "client_secret": IAM_SK
    }
    try:
        response = requests.post(AUTH_URL, data=payload, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        print("成功获取 Access Token。")
        return token_data.get("access_token")
    except requests.exceptions.RequestException as e:
        print(f"获取 Access Token 失败: {e}")
        if e.response: print(f"错误响应: {e.response.text}")
        return None
# =================================================================================

# 用户注册API
@app.route('/api/register', methods=['POST'])
@csrf.exempt
@rate_limit_decorator
def register():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据不能为空"}), 400
    
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({"success": False, "message": "用户名、邮箱和密码不能为空"}), 400
    
    if len(username) < 3 or len(username) > 15:
        return jsonify({"success": False, "message": "用户名长度应在3-15个字符之间"}), 400
    
    if len(password) < 8 or len(password) > 20:
        return jsonify({"success": False, "message": "密码长度应在8-20个字符之间"}), 400
    
    if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
        return jsonify({"success": False, "message": "邮箱格式不正确"}), 400
    
    if not re.match(r'(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])(?=.*[^A-Za-z0-9])', password):
        return jsonify({"success": False, "message": "密码必须包含大小写字母、数字和特殊字符"}), 400
    
    # 防止XSS攻击，对输入进行转义
    username = username.strip()
    email = email.strip()
    
    db = get_db()
    try:
        # 检查用户名是否已存在
        c = db.execute('SELECT id FROM users WHERE username = ?', (username,))
        if c.fetchone():
            return jsonify({"success": False, "message": "用户名已存在"}), 400
        
        # 检查邮箱是否已存在
        c = db.execute('SELECT id FROM users WHERE email = ?', (email,))
        if c.fetchone():
            return jsonify({"success": False, "message": "邮箱已被注册"}), 400
        
        # 密码加密
        hashed_password = hash_password(password)
        
        # 插入用户数据
        db.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                  (username, email, hashed_password))
        db.commit()
        
        return jsonify({"success": True, "message": "注册成功"}), 200
    except Exception as e:
        print(f"注册失败: {e}")
        return jsonify({"success": False, "message": "注册失败，请稍后重试"}), 500

# 用户登录API
@app.route('/api/login', methods=['POST'])
@csrf.exempt
@rate_limit_decorator
def login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据不能为空"}), 400
    
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not password:
        return jsonify({"success": False, "message": "密码不能为空"}), 400
    
    # 防止XSS攻击，对输入进行转义
    if username:
        username = username.strip()
    if email:
        email = email.strip()
    
    db = get_db()
    try:
        # 通过用户名或邮箱查找用户
        if username:
            c = db.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
        elif email:
            c = db.execute('SELECT id, username, password FROM users WHERE email = ?', (email,))
        else:
            return jsonify({"success": False, "message": "用户名或邮箱不能为空"}), 400
        
        user = c.fetchone()
        if not user:
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401
        
        # 验证密码
        if hash_password(password) != user['password']:
            return jsonify({"success": False, "message": "用户名或密码错误"}), 401
        
        # 生成JWT令牌
        token = generate_token(user['id'], user['username'])
        
        return jsonify({"success": True, "message": "登录成功", "token": token, "username": user['username']}), 200
    except Exception as e:
        print(f"登录失败: {e}")
        return jsonify({"success": False, "message": "登录失败，请稍后重试"}), 500

@app.route('/transcribe-audio', methods=['POST'])
@csrf.exempt
def transcribe_audio():
    if 'audio' not in request.files: return jsonify({"error": "请求中未包含音频文件"}), 400
    audio_file = request.files['audio']
    if audio_file.filename == '': return jsonify({"error": "未选择音频文件"}), 400
    
    temp_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], audio_file.filename)
    converted_audio_path = None
    try:
        audio_file.save(temp_audio_path)
        print(f"开始使用讯飞API转写文件: {audio_file.filename}")
        
        # 检查文件格式，如果需要，转换为标准MP3格式
        if temp_audio_path.lower().endswith('.webm') or temp_audio_path.lower().endswith('.ogg') or temp_audio_path.lower().endswith('.mp3'):
            print(f"检测到音频文件，正在转换为标准MP3格式...")
            converted_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], f"converted_{os.path.basename(temp_audio_path).replace('.webm', '.mp3').replace('.ogg', '.mp3').replace('.mp3', '_standard.mp3')}")
            
            # 使用ffmpeg转换音频格式为标准MP3
            import subprocess
            try:
                # 构建ffmpeg命令，确保输出为标准MP3格式
                cmd = [
                    'ffmpeg', '-y', '-i', temp_audio_path,
                    '-acodec', 'libmp3lame', '-b:a', '128k',
                    '-ar', '16000', '-ac', '1',  # 设置为16kHz采样率，单声道
                    converted_audio_path
                ]
                print(f"执行ffmpeg命令: {' '.join(cmd)}")
                
                # 执行命令
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"音频转换成功，保存为: {converted_audio_path}")
                    # 使用转换后的文件
                    temp_audio_path = converted_audio_path
                else:
                    print(f"ffmpeg转换失败: {result.stderr}")
                    # 转换失败，继续使用原始文件
                    print("转换失败，继续使用原始文件")
            except Exception as convert_err:
                print(f"转换音频时出错: {convert_err}")
                # 转换失败，继续使用原始文件
                print("转换失败，继续使用原始文件")
        
        # 检查音频长度，超过60秒则分割
        import subprocess
        audio_duration = 0
        try:
            # 使用ffprobe获取音频时长
            cmd = ['ffprobe', '-i', temp_audio_path, '-show_entries', 'format=duration', '-v', 'quiet', '-of', 'csv=p=0']
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                audio_duration = float(result.stdout.strip())
                print(f"音频时长: {audio_duration}秒")
        except Exception as e:
            print(f"获取音频时长失败: {e}")
        
        # 分割音频文件（如果超过60秒）
        audio_segments = []
        if audio_duration > 60:
            print(f"音频超过60秒，需要分割...")
            segment_count = int(audio_duration / 60) + 1
            for i in range(segment_count):
                start_time = i * 60
                segment_path = os.path.join(app.config['UPLOAD_FOLDER'], f"segment_{i}_{os.path.basename(temp_audio_path)}")
                # 构建ffmpeg分割命令
                cmd = [
                    'ffmpeg', '-y', '-i', temp_audio_path,
                    '-ss', str(start_time), '-t', '60',  # 从start_time开始，截取60秒
                    '-acodec', 'libmp3lame', '-b:a', '128k',
                    '-ar', '16000', '-ac', '1',
                    segment_path
                ]
                print(f"执行分割命令: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"分割成功，保存为: {segment_path}")
                    audio_segments.append(segment_path)
                else:
                    print(f"分割失败: {result.stderr}")
        else:
            # 音频长度在60秒以内，直接使用
            audio_segments = [temp_audio_path]
        
        # 对每个音频片段进行转写
        full_transcription = ""
        for segment_path in audio_segments:
            print(f"转写片段: {segment_path}")
            # 重置全局变量
            global recognition_result, recognition_error, wsParam
            recognition_result = ""
            recognition_error = None
            
            # 创建Ws_Param实例
            wsParam = Ws_Param(APPID, APIKey, APISecret, segment_path)
            
            # 创建WebSocket连接
            websocket.enableTrace(False)
            wsUrl = wsParam.create_url()
            ws = websocket.WebSocketApp(wsUrl, on_message=on_message, on_error=on_error, on_close=on_close)
            ws.on_open = on_open
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 检查是否有错误
            if recognition_error:
                print(f"讯飞API调用失败: {recognition_error}")
                return jsonify({"error": f"讯飞API调用失败: {recognition_error}"}), 500
            
            # 检查是否有识别结果
            if not recognition_result:
                print("讯飞API未返回识别结果")
                return jsonify({"error": "讯飞API未返回识别结果"}), 500
            
            print(f"片段转写结果: {recognition_result}")
            full_transcription += recognition_result
        
        print(f"完整转写结果: {full_transcription}")
        return jsonify({"transcribedText": full_transcription}), 200

    except Exception as e:
        print(f"服务内部错误: {e}")
        return jsonify({"error": f"服务内部错误: {str(e)}"}), 500
    finally:
        # 删除临时文件
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except PermissionError:
                print(f"无法删除文件 {temp_audio_path}，可能被其他进程占用")
        # 删除转换后的文件
        if converted_audio_path and os.path.exists(converted_audio_path):
            try:
                os.remove(converted_audio_path)
            except PermissionError:
                print(f"无法删除文件 {converted_audio_path}，可能被其他进程占用")
        # 删除分割的音频片段
        if 'audio_segments' in locals():
            for segment_path in audio_segments:
                if os.path.exists(segment_path) and segment_path != temp_audio_path:
                    try:
                        os.remove(segment_path)
                    except PermissionError:
                        print(f"无法删除文件 {segment_path}，可能被其他进程占用")

@app.route('/generate-form', methods=['POST'])
@csrf.exempt
def generate_form():
    data = request.get_json()
    print(f"接收到的请求数据: {data}")
    if not data:
        return jsonify({"error": "请求数据不能为空"}), 400
    if 'conversation_text' not in data:
        return jsonify({"error": "缺少conversation_text字段"}), 400
    if not data['conversation_text']:
        return jsonify({"error": "conversation_text字段不能为空"}), 400
    
    conversation_text = data['conversation_text']
    print(f"接收到的conversation_text: {conversation_text}")
    
    try:
        # 简单的量化表生成逻辑，实际项目中可以调用更复杂的AI模型
        quantified_form = {
            "患者信息": {
                "症状描述": conversation_text[:100] + "..." if len(conversation_text) > 100 else conversation_text,
                "问诊时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "医生建议": {
                "初步诊断": "待医生确认",
                "治疗方案": "待医生确认",
                "注意事项": "保持良好作息，注意饮食"
            }
        }
        
        print(f"生成的量化表: {quantified_form}")
        return jsonify(quantified_form), 200
    except Exception as e:
        print(f"生成量化表失败: {e}")
        return jsonify({"error": f"生成量化表失败: {str(e)}"}), 500

if __name__ == '__main__':
    init_db()
    print("Flask 应用正在启动...")
    app.run(debug=True, host='0.0.0.0', port=5000)