#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import copy

from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy


def summarize(policy: SmolVLAPolicy, title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

    total = 0
    trainable = 0

    for name, param in policy.named_parameters():
        n = param.numel()
        total += n
        if param.requires_grad:
            trainable += n
        flag = "trainable" if param.requires_grad else "frozen"
        print(
            f"[{flag:9}] {name:90} shape={str(tuple(param.shape)):25} numel={n:10d} dtype={param.dtype}"
        )

    ratio = 100.0 * trainable / max(total, 1)
    print("-" * 100)
    print(f"trainable/total = {trainable}/{total} ({ratio:.6f}%)")


def build_full_config(base: str):
    # Load once through policy loader so config type-dispatch is handled correctly.
    policy = SmolVLAPolicy.from_pretrained(base)
    cfg = copy.deepcopy(policy.config)
    cfg.freeze_vision_encoder = False
    cfg.train_expert_only = False
    cfg.train_state_proj = True
    cfg.use_lora = False
    cfg.use_lora_expert = False
    return cfg


def build_lora_config(cfg_full, args: argparse.Namespace, use_lora_expert: bool):
    cfg_lora = copy.deepcopy(cfg_full)
    cfg_lora.use_lora = True
    cfg_lora.use_lora_expert = use_lora_expert
    cfg_lora.lora_r = args.lora_r
    cfg_lora.lora_alpha = args.lora_alpha
    cfg_lora.lora_dropout = args.lora_dropout
    cfg_lora.lora_target_modules = args.lora_target_modules
    cfg_lora.lora_bias = args.lora_bias
    return cfg_lora


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare no LoRA, VLM-only LoRA, and VLM+Expert LoRA trainable parameters for SmolVLA.")
    parser.add_argument(
        "--base",
        type=str,
        required=True,
        help="Path to pretrained SmolVLA model directory (e.g. ./myModels/.../pretrained_model).",
    )
    parser.add_argument("--lora_r", type=int, default=8)
    parser.add_argument("--lora_alpha", type=int, default=16)
    parser.add_argument("--lora_dropout", type=float, default=0.05)
    parser.add_argument(
        "--lora_target_modules",
        nargs="+",
        default=["q_proj", "k_proj", "v_proj", "o_proj"],
        help="Space-separated list, e.g. --lora_target_modules q_proj k_proj v_proj o_proj",
    )
    parser.add_argument("--lora_bias", type=str, default="none")
    args = parser.parse_args()

    cfg_full = build_full_config(args.base)
    policy_full = SmolVLAPolicy.from_pretrained(args.base, config=cfg_full)
    policy_full.train()
    summarize(policy_full, "FULL FINETUNE (NO LORA)")

    cfg_lora_vlm_only = build_lora_config(cfg_full, args, use_lora_expert=False)
    policy_lora_vlm_only = SmolVLAPolicy.from_pretrained(args.base, config=cfg_lora_vlm_only)
    policy_lora_vlm_only.train()
    summarize(policy_lora_vlm_only, "LORA FINETUNE (VLM ONLY)")

    cfg_lora_vlm_expert = build_lora_config(cfg_full, args, use_lora_expert=True)
    policy_lora_vlm_expert = SmolVLAPolicy.from_pretrained(args.base, config=cfg_lora_vlm_expert)
    policy_lora_vlm_expert.train()
    summarize(policy_lora_vlm_expert, "LORA FINETUNE (VLM + EXPERT)")


if __name__ == "__main__":
    main()
