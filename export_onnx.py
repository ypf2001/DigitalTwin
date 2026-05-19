"""
ONNX 模型导出 — export_onnx.py
===============================
将 SB3 PPO 模型导出为 ONNX 格式。
输入名 "obs"（23 维归一化观测），输出名 "action"（2 维）。

用法：
    python export_onnx.py --model ./rl_models/ppo_mid_final
    python export_onnx.py --model ./rl_models/best_model --output ./rl_models/policy.onnx
"""

import argparse
import os
import sys
import numpy as np
import torch
import torch.nn as nn

try:
    from stable_baselines3 import PPO
except ImportError:
    print("[ERROR] 请安装 stable-baselines3: pip install stable-baselines3")
    sys.exit(1)

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False


class ActionNet(nn.Module):
    """从 SB3 ActorCriticPolicy 中提取纯动作网络。

    去除 value head、log_std、distribution 验证等，
    只保留 obs → mean_action 的映射。
    """

    def __init__(self, policy):
        super().__init__()
        self.features_extractor = policy.features_extractor
        self.mlp_extractor = policy.mlp_extractor
        self.action_net = policy.action_net

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.features_extractor(x)
        latent_pi, _ = self.mlp_extractor(features)
        return self.action_net(latent_pi)


def export_to_onnx(model, output_path: str):
    """将 PPO 模型导出为 ONNX。

    输入名: "obs",    shape (1, 23) — 归一化观测 [-1, 1]
    输出名: "action", shape (1, 2)  — [q_f, q_a] (0~3, 0~2 L/min)
    """
    policy = model.policy
    policy.eval()

    # 用纯动作网络包装
    action_net = ActionNet(policy)
    action_net.eval()

    dummy_input = torch.randn(1, 23)
    with torch.no_grad():
        demo_action = action_net(dummy_input).numpy().flatten()
    print(f"  策略输出示例: {demo_action}")

    # ---- 导出（关闭 dynamo 使用旧导出器） ----
    torch.onnx.export(
        action_net,
        dummy_input,
        output_path,
        input_names=["obs"],
        output_names=["action"],
        dynamic_axes={
            "obs": {0: "batch_size"},
            "action": {0: "batch_size"},
        },
        opset_version=11,
        do_constant_folding=True,
    )

    print(f"\n[OK] ONNX 已导出: {output_path}")
    print(f"  输入: obs     shape (N, 23)")
    print(f"  输出: action  shape (N, 2)")


def verify_onnx(onnx_path: str):
    """验证 ONNX 模型可用。"""
    if not ONNX_AVAILABLE:
        print("[WARN] onnxruntime 未安装，跳过验证")
        return

    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    # 随机归一化观测 [-1, 1]
    dummy = np.random.uniform(-1, 1, size=(1, 23)).astype(np.float32)
    output = session.run([output_name], {input_name: dummy})[0]

    print(f"\n[ONNX] 验证通过")
    print(f"  输入名: {input_name}  shape {session.get_inputs()[0].shape}")
    print(f"  输出名: {output_name} shape {session.get_outputs()[0].shape}")
    print(f"  示例输出: [q_f={output[0,0]:.4f}, q_a={output[0,1]:.4f}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPO -> ONNX 导出")
    parser.add_argument("--model", type=str, default="./rl_models/ppo_mid_final")
    parser.add_argument("--output", type=str, default="./rl_models/ppo_fertigation.onnx")
    args = parser.parse_args()

    model_path = args.model
    if not model_path.endswith(".zip"):
        model_path += ".zip"

    if not os.path.exists(model_path):
        print(f"[ERROR] 模型不存在: {model_path}")
        print("请先运行 train_ppo.py 训练模型")
        sys.exit(1)

    print(f"[PPO] 加载模型: {model_path}")
    model = PPO.load(model_path)

    export_to_onnx(model, args.output)

    verify_onnx(args.output)

    print("\n[OK] 导出完成")
