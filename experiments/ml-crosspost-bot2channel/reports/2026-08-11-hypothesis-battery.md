# Hypothesis battery 2026-08-11

Bar: top20 f1k lift ≥ v4 + 0.05 on ≥2/3 folds.

| label | id | name | wins | mean_lift | v4_lift | ρ | PASS |
|-------|----|------|-----:|----------:|--------:|---:|:----:|
| 24h | `s_maturity_x_src` | maturity × source | 1/3 | 1.109 | 1.079 | 0.138 | no |
| 24h | `s_v4_x_src` | v4 × source | 1/3 | 1.098 | 1.079 | 0.149 | no |
| 24h | `s_power_x_src` | power × source | 1/3 | 1.098 | 1.079 | 0.148 | no |
| 24h | `s_src_prior` | source prior f1k | 1/3 | 1.017 | 1.079 | 0.042 | no |
| 24h | `s_engaged_x_src` | engaged × source | 0/3 | 1.112 | 1.079 | 0.168 | no |
| 24h | `s_clean_x_src` | no-haters × source | 0/3 | 1.093 | 1.079 | 0.150 | no |
| 24h | `s_mod` | mods/admins only | 0/3 | 1.084 | 1.079 | 0.087 | no |
| 24h | `s_v4_all` | v4 all likes | 0/3 | 1.079 | 1.079 | 0.065 | no |
| 24h | `s_power` | power users (top20% likes) | 0/3 | 1.079 | 1.079 | 0.068 | no |
| 24h | `s_mid_plus` | mid+ users (top50%) | 0/3 | 1.079 | 1.079 | 0.066 | no |
| 24h | `s_not_hater` | exclude serial haters | 0/3 | 1.079 | 1.079 | 0.066 | no |
| 24h | `s_not_rare` | exclude rare users | 0/3 | 1.079 | 1.079 | 0.065 | no |
| 24h | `s_lover` | super-lovers only | 0/3 | 1.079 | 1.079 | 0.057 | no |
| 24h | `s_engaged` | engaged likes only | 0/3 | 1.073 | 1.079 | 0.108 | no |
| 24h | `s_power_engaged` | power × engaged | 0/3 | 1.073 | 1.079 | 0.105 | no |
| 24h | `s_maturity_band` | maturity band volume | 0/3 | 1.051 | 1.079 | 0.038 | no |
| 24h | `s_vol_over_src` | volume / source scale | 0/3 | 1.048 | 1.079 | 0.024 | no |
| 24h | `s_premium` | premium likers | 0/3 | 1.045 | 1.079 | 0.088 | no |
| lifetime | `s_maturity_x_src` | maturity × source | 1/3 | 1.081 | 1.057 | 0.108 | no |
| lifetime | `s_v4_x_src` | v4 × source | 1/3 | 1.081 | 1.057 | 0.110 | no |
| lifetime | `s_clean_x_src` | no-haters × source | 1/3 | 1.080 | 1.057 | 0.102 | no |
| lifetime | `s_power_x_src` | power × source | 1/3 | 1.076 | 1.057 | 0.109 | no |
| lifetime | `s_src_prior` | source prior f1k | 1/3 | 1.073 | 1.057 | 0.094 | no |
| lifetime | `s_engaged_x_src` | engaged × source | 0/3 | 1.070 | 1.057 | 0.123 | no |
| lifetime | `s_v4_all` | v4 all likes | 0/3 | 1.057 | 1.057 | 0.062 | no |
| lifetime | `s_mid_plus` | mid+ users (top50%) | 0/3 | 1.057 | 1.057 | 0.062 | no |
| lifetime | `s_not_rare` | exclude rare users | 0/3 | 1.057 | 1.057 | 0.062 | no |
| lifetime | `s_power` | power users (top20% likes) | 0/3 | 1.051 | 1.057 | 0.059 | no |
| lifetime | `s_mod` | mods/admins only | 0/3 | 1.048 | 1.057 | 0.058 | no |
| lifetime | `s_premium` | premium likers | 0/3 | 1.048 | 1.057 | 0.061 | no |
| lifetime | `s_maturity_band` | maturity band volume | 0/3 | 1.043 | 1.057 | 0.061 | no |
| lifetime | `s_not_hater` | exclude serial haters | 0/3 | 1.037 | 1.057 | 0.053 | no |
| lifetime | `s_lover` | super-lovers only | 0/3 | 1.036 | 1.057 | 0.044 | no |
| lifetime | `s_engaged` | engaged likes only | 0/3 | 1.026 | 1.057 | 0.084 | no |
| lifetime | `s_power_engaged` | power × engaged | 0/3 | 1.018 | 1.057 | 0.082 | no |
| lifetime | `s_vol_over_src` | volume / source scale | 0/3 | 1.001 | 1.057 | 0.010 | no |

## PASS list

- (none cleared bar)

## Closest (by mean lift)

### 24h
- engaged × source: lift 1.112, wins 0, ρ 0.168
- maturity × source: lift 1.109, wins 1, ρ 0.138
- v4 × source: lift 1.098, wins 1, ρ 0.149
- power × source: lift 1.098, wins 1, ρ 0.148
- no-haters × source: lift 1.093, wins 0, ρ 0.150
### lifetime
- maturity × source: lift 1.081, wins 1, ρ 0.108
- v4 × source: lift 1.081, wins 1, ρ 0.110
- no-haters × source: lift 1.080, wins 1, ρ 0.102
- power × source: lift 1.076, wins 1, ρ 0.109
- source prior f1k: lift 1.073, wins 1, ρ 0.094
