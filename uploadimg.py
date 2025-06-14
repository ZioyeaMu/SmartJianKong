import requests
import hashlib
import uuid

def get_md5(value):
    md5 = hashlib.md5()
    md5.update(value.encode('utf-8'))
    return md5.hexdigest()

def upload_image():
    # 配置信息
    API_URL = "https://images.bemfa.com/upload/v1/upimages.php"
    secret_key = "865c32af7d4c73322601d512f8b45b14"  # 替换为你的密钥
    topic_name = "test"
    picpath_value = "LDNYQh"  # 自定义图片路径

    # 计算主题的 md5 值
    topic_md5 = get_md5(secret_key+topic_name)
    print(topic_md5)
    # 构建 picpath 参数
    picpath = f"{secret_key}{topic_md5}{picpath_value}"

    # 要上传的图片路径
    # image_path = "yolov5_master/yolov5/datasets/my_datas/train/non_congested/4243.jpg"  # 替换为你的图片路径
    image_path = "yolov5_master/yolov5/datasets/my_datas/train/congested/10.jpg"

    # 构建请求头
    headers = {
        "Content-Type": "image/jpeg",
        "Authorization": secret_key,
        "Authtopic": topic_name,
        "picpath": picpath_value
    }

    # 读取图片文件
    with open(image_path, "rb") as image_file:
        image_data = image_file.read()

    # 发送POST请求
    response = requests.post(API_URL, headers=headers, data=image_data)
    # 检查响应
    if response.status_code == 200:
        print("图片上传成功")
        print("响应内容:", response.json())
    else:
        print(f"图片上传失败，状态码: {response.status_code}")
        print("响应内容:", response.text)

if __name__ == "__main__":
    upload_image()