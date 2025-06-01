import pandas as pd
import numpy as np

# 定义图的邻接矩阵 (无穷大表示不连通)
INF = float('inf')
graph = [
    [0, 7, 11, INF, INF, INF],
    [7, 0, 10, 9, INF, INF],
    [11, 10, 0, 5, 7, 8],
    [INF, 9, 5, 0, INF, 6],
    [INF, INF, 7, INF, 0, 6],
    [INF, INF, 8, 6, 6, 0]
]

# 初始化
n = len(graph)
start = 0  # 从顶点 1 开始 (数组索引为 0)
dist = [INF] * n
dist[start] = 0
path = [-1] * n
visited = [False] * n

# 记录每一轮的 dist 和 path
iterations = []

# Dijkstra 算法
for _ in range(n):
    # 找到当前未访问点中距离最小的点
    u = -1
    min_dist = INF
    for i in range(n):
        if not visited[i] and dist[i] < min_dist:
            u = i
            min_dist = dist[i]

    if u == -1:  # 如果找不到，说明剩下的点与起点不连通
        break

    visited[u] = True

    # 更新 u 的邻接点的距离
    for v in range(n):
        if graph[u][v] != INF and not visited[v]:
            if dist[u] + graph[u][v] < dist[v]:
                dist[v] = dist[u] + graph[u][v]
                path[v] = u

    # 记录当前轮次的 dist 和 path
    iterations.append({
        'dist': dist[:],  # 当前 dist 数组的拷贝
        'path': path[:]   # 当前 path 数组的拷贝
    })

# 将结果展示为表格
result_data = []
for idx, iteration in enumerate(iterations):
    result_data.append({
        'Iteration': idx + 1,
        'Distances': iteration['dist'],
        'Paths': iteration['path']
    })

df = pd.DataFrame(result_data)

# 直接打印 DataFrame
print(df)
