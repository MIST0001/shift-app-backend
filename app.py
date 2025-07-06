from flask import Flask, jsonify
from flask_cors import CORS # CORSを追加

app = Flask(__name__)
CORS(app) # これでどのサイトからでもAPIにアクセスできるようになる

@app.route("/")
def index():
    return jsonify({"message": "連携成功！Renderからこんにちは！"})
