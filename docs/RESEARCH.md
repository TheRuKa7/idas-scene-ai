# /ultraresearch — iDAS

*State of the field for open-vocabulary object detection and multi-object tracking, as scoped for a 2026 portfolio rebuild. Cites are as of my training cutoff; **verify against current ArXiv + paperswithcode before shipping**.*

## 1. Detection model landscape

| Family | Vocab | Params | Speed (T4 FP16) | License | Verdict for iDAS |
|--------|-------|--------|-----------------|---------|------------------|
| YOLOv8 (Ultralytics) | Closed (80 COCO) | 3–68M | ~3–8 ms | AGPL-3 | Legacy; good baseline |
| YOLOv9 / v10 | Closed | 7–100M | ~3–6 ms | GPL-3 | SOTA closed-vocab speed |
| **YOLO-World** | **Open (text)** | 14–110M | ~8–15 ms | GPL-3 | **Primary v1 backend** |
| RT-DETR (Baidu) | Closed | 20–76M | ~10–15 ms | Apache-2 | Transformer, NMS-free |
| DINO / Grounding DINO 1.5 | Open (text+img) | 172M+ | ~80–120 ms | Apache-2 | Accuracy mode |
| OWLv2 (Google) | Open (text) | 150M+ | ~40–60 ms | Apache-2 | **MIT-compatible fallback** |
| Florence-2 (MS) | Open (multi-task) | 230M–770M | ~200 ms | MIT | Consider for v2 captioning |
| SAM 2 (Meta) | Segmentation + tracking | 80–220M | ~30 ms | Apache-2 | Complement; future v2 |

### Why YOLO-World + OWLv2 dual-track
- **YOLO-World** gives the speed/accuracy Pareto front for open-vocab detection. Built on YOLOv8 backbone with CLIP text encoder.
- **OWLv2** is the Apache-2 safety net. Slower, but license-clean for commercial portfolio messaging.
- Grounding DINO reserved for "accuracy mode" — one-shot high-confidence queries.

## 2. Multi-object tracking (MOT)

| Tracker | Strategy | Strengths | Weakness |
|---------|----------|-----------|----------|
| **ByteTrack** | Motion (Kalman) + low-conf rescue | Fast, robust | Weak on occlusion |
| BoT-SORT | ReID + motion | Best IDF1 on MOT17 | Heavier |
| OC-SORT | Observation-centric | Handles occlusion | More params |
| StrongSORT | Classic DeepSORT++ | Mature | Slower |

**Pick:** ByteTrack for v1. BoT-SORT as opt-in for high-churn scenes.

**Metrics to report:** MOTA, IDF1, HOTA (standard), plus FPS wall-clock.

## 3. Inference runtimes

| Runtime | Platform | Notes |
|---------|----------|-------|
| **ONNX Runtime** | CPU + CUDA + DirectML | Primary for portability |
| TensorRT | NVIDIA GPU | 2-3× speedup, binary artifacts heavy |
| OpenVINO | Intel CPU/GPU/NPU | Laptop inference path |
| TorchScript | Everywhere | Research fallback |
| WebGPU / ONNX-Web | Browser | Future: in-browser demo |

Export pipeline: PyTorch → ONNX (opset 17+) → optional TensorRT engine. Validate numeric parity with fixed seeds.

## 4. Benchmarks & datasets

| Dataset | Classes | Use |
|---------|---------|-----|
| COCO val2017 | 80 | Baseline mAP@50 |
| LVIS v1 val | 1203 (long-tail) | Open-vocab AR@100 |
| ODinW | 13 domains | Open-vocab generalization |
| MOT17 / MOT20 | — | Tracking MOTA/IDF1 |
| BDD100K | Driving | Domain fit for dashcam use-case |

## 5. Relevant papers (anchor reading)

- **YOLO-World**: Cheng et al., *"YOLO-World: Real-Time Open-Vocabulary Object Detection"* (CVPR 2024)
- **Grounding DINO 1.5 Pro**: Ren et al. (2024)
- **YOLOv10**: Wang et al., *"YOLOv10: Real-Time End-to-End Object Detection"* (2024)
- **ByteTrack**: Zhang et al., *"ByteTrack: Multi-Object Tracking by Associating Every Detection Box"* (ECCV 2022)
- **OWLv2**: Minderer et al., *"Scaling Open-Vocabulary Object Detection"* (NeurIPS 2023)
- **SAM 2**: Ravi et al. (Meta, 2024)

## 6. Competitive scan (products)

- Hugging Face Spaces demos (YOLO-World, Grounding DINO) — inspiration only, not productized
- Roboflow Universe — closed-vocab marketplace
- Scale AI / Labelbox — labeling-centric, not detection-as-a-service
- Nvidia Metropolis — enterprise CCTV analytics
- **Gap to fill:** a clean OSS reference for open-vocab video scene understanding with tracking + scene JSON. Most demos stop at single-image detection.

## 7. Open questions to resolve before P1

- [ ] YOLO-World ONNX export numerical parity vs PyTorch (±0.5% mAP acceptable?)
- [ ] ByteTrack on open-vocab detections (tracker assumes stable class IDs — how to handle prompt changes mid-video?)
- [ ] Dashcam-specific finetuning: is BDD100K worth the effort for v1 or v2?
- [ ] Browser inference feasibility: YOLO-World ONNX size (~200MB) vs WebGPU limits
