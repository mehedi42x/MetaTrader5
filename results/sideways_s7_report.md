# Sideways filters on the S7 order-block system (M1)

S7 = the order-block retest system (swing structure size 50, BOS/CHoCH stores the block, a retest fills at the block edge, exit on structure flip or block failure). 0.01 lot, $0.20 per trade. Filters are applied both when the order is armed (at the break) and when it fills (at the retest).

| filter | 2022 | 2023 | 2024 | 2025 | 4-year total | positive years |
|---|---|---|---|---|---|---|
| no filter | $702.03 (1337) | $642.25 (1215) | $847.86 (1388) | $1,932.44 (1341) | **$4,124.58** | 4/4 |
| arm+fill ADX>25 | $92.70 (383) | $199.68 (358) | $180.93 (408) | $6.95 (398) | **$480.26** | 4/4 |
| arm+fill ADX>30 | $63.61 (174) | $54.91 (142) | $53.38 (172) | $15.77 (160) | **$187.67** | 4/4 |
| arm+fill Chop<38.2 | $25.72 (177) | $48.43 (227) | $-0.59 (227) | $57.57 (159) | **$131.13** | 3/4 |
| arm+fill Chop<45 | $212.68 (542) | $175.67 (544) | $160.45 (596) | $504.00 (539) | **$1,052.80** | 4/4 |
| arm+fill ER>0.3 | $285.17 (814) | $304.50 (718) | $368.52 (852) | $893.51 (841) | **$1,851.70** | 4/4 |
| arm+fill ER>0.4 | $192.61 (573) | $167.47 (488) | $239.90 (612) | $610.36 (613) | **$1,210.34** | 4/4 |
| arm+fill ATRratio>1.0 | $55.92 (615) | $169.10 (592) | $107.93 (616) | $429.62 (569) | **$762.57** | 4/4 |
| arm+fill ATRratio>1.2 | $-11.05 (84) | $-91.15 (98) | $-91.76 (91) | $30.89 (82) | **$-163.07** | 1/4 |
| fill-only ADX>25 | $104.23 (616) | $195.77 (546) | $237.07 (645) | $497.04 (625) | **$1,034.11** | 4/4 |
| fill-only Chop<45 | $236.33 (705) | $234.06 (659) | $242.44 (754) | $589.59 (711) | **$1,302.42** | 4/4 |
| fill-only ER>0.3 | $352.35 (901) | $343.03 (781) | $447.21 (941) | $813.00 (931) | **$1,955.59** | 4/4 |
| arm+fill Chop<45 & ER>0.3 | $195.89 (435) | $164.39 (421) | $55.16 (471) | $356.65 (455) | **$772.09** | 4/4 |
| arm+fill ADX>25 & ER>0.3 | $91.37 (229) | $190.04 (217) | $62.07 (235) | $-119.20 (244) | **$224.28** | 3/4 |

## Recent check — real Exness MT5 M1, 9-18 September 2026

| variant | trades | net $ | win% | PF | max DD $ |
|---|---|---|---|---|---|
| no filter | 30 | $149.70 | 23.3% | 3.21 | $-27.79 |
| fill-only ER>0.3 | 26 | $161.27 | 26.9% | 3.87 | $-25.29 |
| arm+fill Chop<45 | 7 | $52.18 | 14.3% | 3.73 | $-12.48 |
| arm+fill ADX>25 | 7 | $93.97 | 28.6% | 6.24 | $-17.92 |

Chart: results/sideways_s7.png | recent: results/sideways_s7_recent.png
