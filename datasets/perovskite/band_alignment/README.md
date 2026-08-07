# 钙钛矿太阳能电池能带对齐优化评测集 — band_alignment

## 数据集信息

| 属性 | 值 |
| --- | --- |
| 领域 | 钙钛矿太阳能电池 (Perovskite Solar Cells) |
| 评测用途 | 太阳能电池能带与电子/空穴传输层 (ETL/HTL) 参数黑盒优化 |
| 优化目标 | 最大化 `eta` (%) 光电转换效率 (PCE) |
| 优化变量数量 | 5 |
| 搜索空间样本数 | 999 |
| 默认训练集样本数 | 10 |
| 测试样本数 | 989 |

## 特征与目标说明

| 列名 | 说明 |
| --- | --- |
| `CHI_PVK` | 钙钛矿层电子亲和能 (Electron Affinity, eV) |
| `Eg_HTL` | 空穴传输层 (HTL) 禁带宽度 (Band Gap, eV) |
| `CHI_HTL` | 空穴传输层 (HTL) 电子亲和能 (eV) |
| `Eg_ETL` | 电子传输层 (ETL) 禁带宽度 (Band Gap, eV) |
| `CHI_ETL` | 电子传输层 (ETL) 电子亲和能 (eV) |
| `eta` | 目标光电转换效率 (%) |

## 文件结构

- `searchspace.csv`: 完整 999 条候选搜索空间（包含 `eta`）。
- `train.csv`: 默认 10 条带标签初始化训练集。
- `test.csv`: 测试集中带标签数据（作为实际实验结果反馈）。
- `test_features.csv`: 测试集中不含 `eta` 的特征池（提供给 Agent 探索）。
- `options.json`: 各特征列的可选项及取值区间。
