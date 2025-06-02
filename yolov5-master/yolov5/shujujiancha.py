# 类别分布检查
from collections import Counter
labels = []
for split in ['train', 'val']:
    for cls_dir in Path(f"data/my_datas/{split}").iterdir():
        if cls_dir.is_dir():
            labels.extend([cls_dir.name]*len(list(cls_dir.glob("*.*"))))
print(Counter(labels))