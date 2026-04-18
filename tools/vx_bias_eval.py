from pathlib import Path
import os
import time
import numpy as np
import torch

os.environ.setdefault("LEROBOT_SRC", "/home/jetson/Shu/lerobot/src")

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from vla.model.smol_vla_policy import SmolVLAPolicyWrapper


def main():
    model_id = "/home/jetson/Shu/smol_rugv/models/smolvla_ugv_moveaway_finetune/checkpoints/last/pretrained_model"
    root = Path("tools/ugv_data_collector/datasets/myusername/ugv-moveaway-task")

    ds = LeRobotDataset("myusername/ugv-moveaway-task", root=root, video_backend="pyav")
    n = min(200, len(ds))
    print(f"N={n}")

    wrapper = SmolVLAPolicyWrapper(model_id, device="cuda")
    raw_vx = []
    post_vx = []
    report_every = 10
    t0 = time.time()

    for i in range(n):
        x = ds[i]
        obs = {
            "observation.images.camera": x["observation.images.camera"],
            "observation.state": x["observation.state"],
            "task": x.get("task", "move away from the column"),
        }
        batch = wrapper.preprocess(obs)
        with torch.no_grad():
            chunk = wrapper.step(batch)
            raw = float(chunk[0, 0, 0].detach().cpu())
            post = wrapper.postprocess(chunk)
            if isinstance(post, torch.Tensor):
                post_first = float(post[0, 0, 0].detach().cpu())
            else:
                post_first = float(np.asarray(post)[0, 0, 0])

        raw_vx.append(raw)
        post_vx.append(post_first)

        done = i + 1
        if done == 1 or done % report_every == 0 or done == n:
            elapsed = time.time() - t0
            per_item = elapsed / done
            eta = per_item * (n - done)
            print(
                f"progress {done}/{n} | elapsed={elapsed:.1f}s | avg={per_item:.3f}s/item | eta={eta:.1f}s",
                flush=True,
            )

    for name, arr in (("raw", np.asarray(raw_vx)), ("post", np.asarray(post_vx))):
        print(f"--- {name}")
        print(
            f"mean={arr.mean():+.6f} std={arr.std():.6f} min={arr.min():+.6f} max={arr.max():+.6f}"
        )
        print(
            f"pos_ratio={(arr > 0).mean():.4f} neg_ratio={(arr < 0).mean():.4f} zero_ratio={(arr == 0).mean():.4f}"
        )


if __name__ == "__main__":
    main()
