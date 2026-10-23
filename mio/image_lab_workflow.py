"""IMG2A: bounded FLUX.2 Klein 4B ComfyUI graph builders, no model execution here."""
from __future__ import annotations

import re

from mio.studio_files import StudioError

UNET = "flux-2-klein-4b-fp8.safetensors"
ENCODER = "qwen_3_4b.safetensors"
VAE = "flux2-vae.safetensors"
REQUIRED = ("UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "ConditioningZeroOut",
            "CFGGuider", "RandomNoise", "KSamplerSelect", "Flux2Scheduler",
            "SamplerCustomAdvanced", "EmptyFlux2LatentImage", "VAEDecode", "SaveImage")
EDIT_REQUIRED = ("LoadImage", "VAEEncode", "ReferenceLatent")


def _node(kind: str, **kwargs: object) -> dict:
    return {"class_type": kind, "inputs": kwargs}


def _out(key: str) -> list:
    return [key, 0]


def _dimensions(width: int, height: int) -> tuple[int, int]:
    if not all(isinstance(n, int) for n in (width, height)) or not 256 <= width <= 2048 or not 256 <= height <= 2048:
        raise StudioError("Reference dimensions must be 256–2048 pixels")
    if width * height > 3_000_000:
        raise StudioError("Reference image is too large for this editing preset")
    scale = min(1024 / width, 1024 / height)
    return (max(256, min(1024, round(width * scale / 16) * 16)),
            max(256, min(1024, round(height * scale / 16) * 16)))


def build_flux(prompt: str, seed: int, job_id: str, *, reference: str | None = None,
               dimensions: tuple[int, int] = (1024, 1024)) -> dict:
    """The tested IMG1C 4-step Euler/CFG=1 topology; edit includes true ReferenceLatent."""
    if not isinstance(prompt, str) or not 4 <= len(prompt.strip()) <= 1200:
        raise StudioError("Invalid image prompt")
    if not isinstance(seed, int) or not 0 <= seed < 2**48:
        raise StudioError("Invalid seed")
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise StudioError("Invalid image job ID")
    if reference is not None and not re.fullmatch(r"mio-img2a-[0-9a-f]{32}\.(png|jpg|jpeg)", reference):
        raise StudioError("Unsafe ComfyUI reference image filename")
    width, height = (1024, 1024) if reference is None else _dimensions(*dimensions)
    graph = {
        "10": _node("UNETLoader", unet_name=UNET, weight_dtype="default"),
        "11": _node("CLIPLoader", clip_name=ENCODER, type="flux2", device="default"),
        "12": _node("VAELoader", vae_name=VAE),
        "13": _node("CLIPTextEncode", clip=_out("11"), text=prompt),
        "14": _node("ConditioningZeroOut", conditioning=_out("13")),
        "15": _node("CFGGuider", model=_out("10"), positive=_out("13"),
                    negative=_out("14"), cfg=1),
        "16": _node("KSamplerSelect", sampler_name="euler"),
        "17": _node("Flux2Scheduler", steps=4, width=width, height=height),
        "18": _node("EmptyFlux2LatentImage", width=width, height=height, batch_size=1),
        "19": _node("RandomNoise", noise_seed=seed),
        "20": _node("SamplerCustomAdvanced", noise=_out("19"), guider=_out("15"),
                    sampler=_out("16"), sigmas=_out("17"), latent_image=_out("18")),
        "21": _node("VAEDecode", samples=_out("20"), vae=_out("12")),
        "22": _node("SaveImage", filename_prefix=f"MioAgent_IMG2A_{job_id}", images=_out("21")),
    }
    if reference is not None:
        graph["23"] = _node("LoadImage", image=reference)
        graph["24"] = _node("VAEEncode", pixels=_out("23"), vae=_out("12"))
        graph["25"] = _node("ReferenceLatent", conditioning=_out("13"), latent=_out("24"))
        graph["26"] = _node("ReferenceLatent", conditioning=_out("14"), latent=_out("24"))
        graph["15"]["inputs"].update(positive=_out("25"), negative=_out("26"))
    return graph
