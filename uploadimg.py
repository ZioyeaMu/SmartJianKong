import requests

# 设置API接口URL
url = 'https://apis.bemfa.com/vb/api/v1/imagesUpload'

# 准备请求的参数
openID = '865c32af7d4c73322601d512f8b45b14'  # 用户私钥
topic = 'test'     # 主题名称
wechat = None           # 是否发送到微信公众号，可以设置为None或填入微信号
pash = None             # 是否自定义地址，可以设置为None或填入自定义地址

# 打开要上传的图片文件
image_path = "F:\\PyCharm\\SmartJianKong\\test_img\\001.jpg"  # 图片路径

# 构建请求体
files = {
    'image': open(image_path, 'rb')  # 以二进制方式打开文件
}
data = {
    'openID': openID,
    'topic': topic,
    'wechat': wechat if wechat else '',  # 如果wechat是None，则不传递
    'pash': pash if pash else '',        # 如果pash是None，则不传递
}

# 发送POST请求
response = requests.post(url, data=data, files=files)

# 关闭文件
files['image'].close()

# 处理响应
if response.status_code == 200:
    # 解析JSON响应
    result = response.json()
    if result['code'] == 0:
        print("上传成功！")
        print(f"图片URL: {result['data']['url']}")
        print(f"主题: {result['data']['topic']}")
        print(f"上传时间: {result['data']['time']}")
    else:
        print(f"上传失败: {result['msg']}")
else:
    print(f"请求失败, 状态码: {response.status_code}")
