v1_elas = 10.5
v1_reg = abs(58 - 79) * 0.5  
print("V1 Cost (reduced W_REG):", v1_elas + v1_reg)
v2_elas = 0.0
v2_reg = abs(58 - 61.6) * 0.75
v2_top_punish = 20.0
print("V2 Cost:", v2_elas + v2_reg + v2_top_punish)
