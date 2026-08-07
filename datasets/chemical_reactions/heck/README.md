# Direct Arylation (BMS-911543) — DOLE 数据集

## 来源
- **论文**: Shields BJ, Stevens J, Li J, et al. "Bayesian Reaction Optimization as a Tool for Chemical Synthesis." *Nature*, 2021.
- **代码**: [b-shields/edbo](https://github.com/b-shields/edbo)
- **反应**: 钯催化的直接芳基化（Direct Arylation），BMS-911543（JAK2 抑制剂）合成关键步骤
- **底物**: 2-甲氧基-4-(三氟甲氧基)苯胺 + 4-氯硝基苯 → 目标产物

## 搜索空间
4 Base × 12 Ligand × 4 Solvent × 3 Concentration × 3 Temp = **1728 种反应条件组合**

| 变量 | 类型 | 取值数 | 说明 |
| --- | --- | --- | --- |
| Base | 离散 | 4 | KOAc, KOPiv, CsOAc, CsOPiv |
| Ligand | 离散 | 12 | BrettPhos, PPhtBu2, X-Phos, PCy3 HBF4 等 |
| Solvent | 离散 | 4 | DMAc, BuCN, BuOAc, p-Xylene |
| Concentration_M | 连续（离散化） | 3 | 0.057, 0.100, 0.153 M |
| Temp_C | 连续（离散化） | 3 | 90, 105, 120 °C |

## 数据集文件
| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `searchspace.csv` | 1728 | 完整搜索空间（含 Yield） |
| `train.csv` | 172 | 10% 随机初始化训练集（含 Yield） |
| `test.csv` | 1556 | 测试集（含 Yield，组织者/结果查询用） |
| `test_features.csv` | 1556 | 未标注候选池（供 BO Agent 探索） |
| `options.json` | — | 各特征候选值列表 |

## 列名说明
| 列 | 类型 | 说明 |
| --- | --- | --- |
| Base | str | 碱 |
| Ligand | str | 配体 |
| Solvent | str | 溶剂 |
| Concentration_M | str | 底物浓度 (M) |
| Temp_C | str | 反应温度 (°C) |
| Yield | float | 反应产率 (%)，优化目标（最大化） |

## 数据统计
- **均值**: ~19.4%
- **中位数**: ~8.1%
- **最大值**: 100%
- **分布**: 高度右偏，大量 0% 产率样本

## 注意事项
1. `Concentration_M` 和 `Temp_C` 在原数据中是连续变量，为兼容当前离散 BO 框架做了离散化（3 个离散水平）
2. 若要在连续空间优化，可取消离散化直接使用浮点值
3. 这是全搜索空间数据（1728 = 4×12×4×3×3），所有组合均有标注，实际 BO 场景中部分组合可能未测量

## 与其他数据集对比
| 数据集 | 变量数 | 搜索空间大小 | 连续变量 | 训练集大小 |
| --- | --- | --- | --- | --- |
| Heck (本集) | 5 | 1728 | 2（已离散化） | 172 |
| Buchwald_sub4 | 4 | 792 | 无 | 35 |
| Suzuki | 4 | 560 | 无 | 29 |
