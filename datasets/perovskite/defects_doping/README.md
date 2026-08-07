# 钙钛矿太阳能电池缺陷与掺杂优化评测集 — defects_doping

## 数据集信息

| 属性 | 值 |
| --- | --- |
| 领域 | 钙钛矿太阳能电池 (Perovskite Solar Cells) |
| 评测用途 | 界面缺陷态密度与各层掺杂浓度黑盒优化 |
| 优化目标 | 最大化 `eta` (%) 光电转换效率 (PCE) |
| 优化变量数量 | 8 |
| 搜索空间样本数 | 998 |
| 默认训练集样本数 | 10 |
| 测试样本数 | 988 |

## 特征与目标说明

| 列名 | 说明 |
| --- | --- |
| `Nt_PVK/ETL` | PVK/ETL 界面缺陷态密度 ($\text{cm}^{-3}$) |
| `Nt_HTL/PVK` | HTL/PVK 界面缺陷态密度 ($\text{cm}^{-3}$) |
| `Na_PVK` | 钙钛矿层受主掺杂浓度 ($\text{cm}^{-3}$) |
| `Nd_PVK` | 钙钛矿层施主掺杂浓度 ($\text{cm}^{-3}$) |
| `Na_HTL` | HTL 层受主掺杂浓度 ($\text{cm}^{-3}$) |
| `Nd_HTL` | HTL 层施主掺杂浓度 ($\text{cm}^{-3}$) |
| `Na_ETL` | ETL 层受主掺杂浓度 ($\text{cm}^{-3}$) |
| `Nd_ETL` | ETL 层施主掺杂浓度 ($\text{cm}^{-3}$) |
| `eta` | 目标光电转换效率 (%) |

## 文件结构

- `searchspace.csv`: 完整 998 条候选搜索空间（包含 `eta`）。
- `train.csv`: 默认 10 条带标签初始化训练集。
- `test.csv`: 测试集中带标签数据（作为实际实验结果反馈）。
- `test_features.csv`: 测试集中不含 `eta` 的特征池（提供给 Agent 探索）。
- `options.json`: 各特征列的可选项及取值区间。
