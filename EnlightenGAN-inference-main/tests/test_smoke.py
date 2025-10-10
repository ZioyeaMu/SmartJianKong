import cv2
from enlighten_inference import EnlightenOnnxModel   # 包名别写错
from onnxruntime import InferenceSession, get_device

file = 'Screenshot_2025-09-09-17-28-09-249_tv.danmaku.bil.jpg'

def test_smoke():
    # 1. 模型只初始化一次，别放循环里
    model = EnlightenOnnxModel(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])

    print("ONNX device:", get_device())  # 期望输出 GPU
    print("Providers:", model.graph.get_providers())  # 期望 ['CUDAExecutionProvider', ...]
    print(model.graph.get_providers() == ["CUDAExecutionProvider", "CPUExecutionProvider"])

    # 2. cv2.imread 读不到返回 None，要判断
    img = cv2.imread(file)
    if img is None:
        raise FileNotFoundError(f'{file} 不在当前目录')

    processed = model.predict(img)

    # 3. cv2.imshow 必须带窗口名 + waitKey，否则闪退
    cv2.namedWindow('before', cv2.WINDOW_NORMAL)
    cv2.namedWindow('after', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('before', 800, 600)
    cv2.resizeWindow('after', 800, 600)
    cv2.imshow('before', img)
    cv2.imshow('after', processed)
    cv2.waitKey(0)          # 按任意键关闭
    cv2.destroyAllWindows()

    assert img.shape == processed.shape
    assert img.mean() < processed.mean()
    print('OK!')

if __name__ == '__main__':
    test_smoke()