import cv2
import numpy as np
from yolov5.utils.dataloaders import ClassificationDataset

# 初始化数据集
dataset = ClassificationDataset(
    root="D:/TrafficSystem/yolov5-master/yolov5/data/my_datas",
    imgsz=224,
    augment=False,
    cache=False
)

# 测试读取
for i in range(min(5, len(dataset))):  # 检查前5个样本
    img, label = dataset[i]
    print(f"样本{i}: 标签={label}, 形状={img.shape}")
    cv2.imshow(f"Sample {i}", img[..., ::-1])  # BGR转RGB显示
    cv2.waitKey(1000)
cv2.destroyAllWindows()