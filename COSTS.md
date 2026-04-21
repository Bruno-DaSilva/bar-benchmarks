# Costs

Back-of-the-envelope cost for a single invocation of `bar-benchmarks` on GCP.
Numbers are rough planning estimates, not quotes — rerun the math once the
final instance shape is pinned.

## Assumptions

| Parameter                    | Value                         | Notes                                    |
|------------------------------|-------------------------------|------------------------------------------|
| Cloud                        | GCP Batch (on Compute Engine) | Batch itself is free; you pay for the underlying VMs. |
| Machine family               | N1, Skylake CPU platform      | `minCpuPlatform: "Intel Skylake"`        |
| VM unit price (spot)         | $0.14 / hr                    | User-provided estimate                   |
| Boot disk                    | 50 GB, pd-balanced            | $0.10 / GB-month, billed per second      |
| Runs per invocation          | 20                            | One Batch Task per run, taskCount=parallelism=20 |
| Scenario duration            | 8 min                         |                                          |
| Preflight microbench         | 1 min                         |                                          |
| Spawn / boot / artifact stage | 2 min                        | Batch VM boot + GCS-FUSE mount of artifacts bucket |
| Collector upload + teardown  | 1 min                         | Write `results.json` to mounted GCS bucket |
| **End-to-end per VM**        | **~12 min** (0.2 hr)          |                                          |

All 20 VMs run in parallel, so wall-clock per invocation is ~12 min and
billable VM-time is 20 × 12 min = **4 VM-hours**.

## Per-invocation math

### Compute

```
20 VMs × 0.2 hr × $0.14/hr  =  $0.56
```

### Boot disk (pd-balanced, 50 GB, per-second billing)

```
monthly cost per VM   = 50 GB × $0.10/GB-mo  = $5.00 / month
seconds in a month    ≈ 2,628,000 s          (30-day month)
per-second rate       = $5.00 / 2,628,000    ≈ $0.0000019 /s
per VM (720 s)        ≈ $0.0014
20 VMs                ≈ $0.027
```

### Egress

- **GCS → VM (same region):** free. The five artifacts should live in a GCS
  bucket in the same region as the VMs, so downloading them to each VM
  costs $0.
- **VM → GCS (same region):** free. `results.json` upload costs $0.
- **Cross-region or internet egress:** $0.12/GB to internet, $0.01/GB
  between GCP regions. Keep everything co-located and this line is zero.

### Ephemeral external IP

GCE charges ~$0.005/hr per ephemeral external IPv4 while the VM is running:

```
20 VMs × 0.2 hr × $0.005/hr  =  $0.02
```

Avoidable if VMs use internal IPs only and pull artifacts via a VPC
endpoint — probably not worth optimizing for at this scale.

### GCS storage for artifacts + results

Negligible. 5 artifacts × maybe 1 GB each × $0.02/GB-month is $0.10/month
for the whole bucket; per-invocation share is effectively $0.

### Bottom line

| Line item               | Cost per invocation |
|-------------------------|---------------------|
| Compute (20 × 12 min)   | $0.56               |
| Boot disks              | $0.03               |
| Egress (same region)    | $0.00               |
| External IPs            | $0.02               |
| GCS storage             | ~$0.00              |
| GCP Batch service fee   | $0.00               |
| **Total**               | **~$0.61**          |

Round up to **~$1 per invocation** to cover preflight re-spawns and slack.

## Scaling

Assuming the per-VM time stays at 12 min and same pricing:

| Runs per invocation | VM-hours | Compute cost |
|---------------------|----------|--------------|
| 10                  | 2.0      | $0.28        |
| 20                  | 4.0      | $0.56        |
| 50                  | 10.0     | $1.40        |
| 100                 | 20.0     | $2.80        |
| 500                 | 100.0    | $14.00       |

Compute is linear in N. Disk and IP scale linearly too but remain rounding
errors. The tool can do a lot of benchmark iterations cheaply as long as
runs stay short and parallel.

## Sensitivities

These are the knobs that most change the bottom line:

- **Scenario duration.** Each extra minute adds ~$0.047 per invocation at
  N=20. An 8-min scenario → 16-min scenario roughly doubles compute cost.
- **Instance size.** $0.14/hr is the given estimate; a bigger instance
  (e.g. n1-highcpu-16) can be 3–4× that. The ratio of on-demand to spot
  price on N1 is typically ~3×.
- **Spot preemption.** Short runs (~12 min) have low preemption risk, but
  GCP can reclaim a spot VM with 30 s notice. A preempted run is just an
  invalid run — re-running it is the cost of a normal VM. At N=20 and
  modest preemption rates, expect 0–1 re-runs per invocation on average.
- **Region.** Cheapest regions (`us-central1`, `us-east1`) are roughly
  10–20% below the more expensive ones. Keep the artifact bucket in the
  same region to preserve free egress.
- **Preflight rejections.** A VM that fails preflight still costs the boot
  + preflight time (~3 min × $0.14/hr ≈ $0.007 per rejection). Cheap enough
  that aggressive rejection is fine.
- **Machine family choice.** N1 is older. N2, T2D, and C3 families often
  give better per-dollar performance for CPU-bound workloads, but Skylake
  pinning is only available on N1, so stay here if reproducibility across
  CPU generations is the priority.

## Ways to reduce cost (if ever needed)

At this scale, cost is not the bottleneck; time-to-signal is. But if future
N gets large:

- Smaller boot disk (20 GB instead of 50) cuts disk cost in half. Check
  that artifacts + working set fit.
- Regional artifact bucket + internal-only IPs to guarantee zero egress.
- Single shared GCS read-through cache if the same artifacts are reused
  across many invocations (avoids re-hashing / re-staging, but does not
  affect per-invocation cost).
- Switch from pd-balanced to pd-standard ($0.04/GB-month) if disk IOPS
  aren't a factor in the benchmark — halves an already tiny line item.
