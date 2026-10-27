# opsKit analysis: inventory, troubleshooting automation, and proposed libraries

Prepared for Ram Vallamsetti, Monday Oct 26, 2026. This is the only file this change adds; no existing file was modified.

The main focus is **turning the troubleshooting content in Ram's SRE docs into two independent automation libraries**: one for **EKS on Fargate** and one for **ECS on Fargate** (with notes on the EC2 launch type). They cover the full cluster-management error surface: workloads/pods, cluster, nodes, networking, load balancing and timeouts. Sections 7-12 hold the opsKit inventory, the Lambda findings and the other proposed libraries.

Contents

1. How to read this document (doc keys and labels)
2. SRE doc inventory
3. Troubleshooting knowledge base: errors, doc steps, automatability
4. Library 1: `opskit.eks_fargate_troubleshoot`
5. Library 2: `opskit.ecs_fargate_troubleshoot`
6. Side-by-side error mapping (EKS Fargate vs ECS Fargate)
7. opsKit inventory (as of commit `b42a3e1`)
8. AWS Lambda findings
9. Shared opsKit patterns
10. Other proposed libraries
11. Priority order
12. Issues found in existing code (not fixed here)

---

## 1. How to read this document

| Key | Document | Sections used |
|---|---|---|
| **D1** | *Kubernetes, Helm & Istio Visual Field Guide* (`/workspace/k8s-guide/K8s_Guide_Part1-3.pdf`) | Part 2 playbooks A1-A4, R1-R5, N1-N4, L1-L4, C1-C7; Part 3 §3.1 error-code reference; §1.5.1 PDBs; §1.7 Linux internals |
| **D2** | *Kubernetes Platform and Blue-Green Deployment* (`/workspace/k8s-bluegreen/...docx`) | §4 node/pod failures, §5.1 workflow, §5.2 troubleshooting table, §5.3 remediation, §5.4 cheat sheet, §3.2/§3.6 switching and rollback |
| **D3** | *Amazon SDE III Prep* | Linux / networking troubleshooting lists |
| **D4** | *Amazon SysDE III Prep (Concise)* | "Linux / troubleshooting quick list", safe-rollout design |
| **D5** | *Intuit Staff App Ops Interview Prep* | Q1 500 vs 504, Q8 circuit breaker (ECS deployment circuit breaker), SLO/error budget, MTTD/MTTR |
| **D6** | *Data Structures Interview Questions: Platform and SRE* | P10 rate limiter, P13 error-rate window, S6 health aggregation, S7 rollback, S8 retry |
| **D7** | *Career Facts* (`/workspace/resume/experience_stories.docx`) | Incident Response STAR story |
| **D8** | *Ripple Recruiter Prep* + D1 Part 4.6 | EKS data plane: "Fargate: no nodes, per-pod pricing, but no DaemonSets or privileged pods" |

- **[doc: D1 A1]** means the step comes from that doc and section.
- **(standard practice, not in docs)**, shortened to **SP**, means the docs don't cover the step and it was filled in from standard AWS/Kubernetes practice. The docs target self-managed or EC2-backed clusters (labs run on kind), so **almost all ECS content and every Fargate-specific step is SP.**
- **Detect** = found with read-only APIs. **Auto-fix** = safe to remediate behind `--apply` + `ChangeBudget`. **Suggest** = the library prints a recommended change and never runs it.

---

## 2. SRE doc inventory (read-only scan of the box, Oct 26, 2026)

Read with python-docx and pdftotext. Cover letters skipped as requested. Backups (`*_backup`, `*_pre_*`) are listed once under the current version.

| Path | One-line summary |
|---|---|
| `/workspace/k8s-guide/K8s_Guide_Part1-3.pdf` | **D1.** Visual field guide: K8s architecture, Linux internals (cgroups, netns), Helm, Istio, runnable kind labs for every troubleshooting playbook, 4xx/5xx/exit-code reference. The richest troubleshooting source. |
| `/workspace/k8s-guide/k8s_helm_istio_visual_guide.pdf` | Combined edition of D1 Parts 1-5 (older snapshots `*_pre_part5`, `*_pre_set2`, `*.backup_2026-10-15`). |
| `/workspace/k8s-guide/K8s_Guide_Part4-5_Ripple_XRPL.pdf` | D1 Parts 4-5: Ripple prep (EKS, Linux, networking, Prometheus) and an XRPL primer. |
| `/workspace/k8s-bluegreen/Kubernetes-Platform-and-Blue-Green-Deployment.docx` (+ `.pdf`; `/workspace/arch.docx` is identical) | **D2.** Engineering reference: Service vs Ingress, blue-green with automatic switching, node/pod failures, Pending/Terminating/restart table, observability, EKS/AKS/GKE, multi-cloud facade, pipelines. |
| `/workspace/interview-guide/SageMaker_MLOps_Guide_with_Mock_QA.docx` (+ `render/*.pdf`, `_pre_aiops`) | SageMaker MLOps guide for the NVIDIA Staff SRE (AI Platform Runtime) interview: pipelines, registry, deployment, monitoring, GPU/LLM serving (NIM/Triton), failure modes, mock Q&A. **The GPU-infrastructure content on the box**; no standalone "GPU infrastructure explainer" file exists. |
| `/workspace/interview-guide/nvidia_zoox_guide.pdf` | One-page NVIDIA/Zoox quick sheet: likely questions with cues, strengths vs gaps. |
| `/workspace/interview_prep/Zoox_Prep.docx` (PDF in `/workspace/interview_prep_build/pdf/`) | Zoox recruiter-call prep. |
| `/workspace/interview/intuit/Intuit_Staff_AppOps_Interview_Prep.docx` (+ `_Visual`, PDFs) | **D5.** Intuit Staff App Ops phone-screen debrief: transcript, 15-question scorecard (500 vs 504, circuit breaker, SLO, MTTD/MTTR, DR), gaps. |
| `/workspace/interview_prep/Amazon_SDE_III_Prep.docx` (+ `.pdf`) | **D3.** Amazon SDE/SysDE III (EC2 Nitro) prep: LP stories, Linux/networking command lists, system design. |
| `/workspace/interview_prep/Amazon_SysDE_III_Prep_Concise.docx` (+ `.pdf`) | **D4.** Concise version: Linux quick list (df -h/-i, lsof +L1, dig→traceroute→nc→openssl→curl), safe fleet rollout. |
| `/workspace/interview_prep/Amazon_SDE_Nitro_Operational_Health_Answer.docx` | Operational-health STAR stories and an SRE day-to-day (Dynatrace/Splunk, compliance). |
| `/workspace/interview_prep/Amazon_SDE_Nitro_Phone_Screen_Debrief_2026-10-20.docx` | Amazon Nitro phone-screen debrief. |
| `/workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx` (+ `.pdf`, `_pre_visual`, `_backup`) | **D6.** 24 problems + 9 SRE scenarios with tested Python; source of `src/data-structures/`. |
| `/workspace/interview_prep/Mirantis_Interview_Prep_2026-10-19.docx` | Mirantis (K8s/KubeVirt) cheat sheet, 30/60/90 plan. |
| `/workspace/interview_prep/Ripple_Recruiter_Prep.docx` (+ `.pdf`) | **D8.** Ripple Platform SWE prep: EKS/K8s/Linux/networking Q&A. |
| `/workspace/interview_prep/XRPL_Visual_Guide.docx` (+ `.pdf`, `pre_*`, `xrpl_visuals/`) | XRP Ledger study infographics. |
| `/workspace/interview_prep/ServiceNow_Prep.docx`, `ServiceNow_Cheat_Sheet.docx` (+ PDFs) | ServiceNow Federal ATG ML-ops screen prep (K8s, KServe/Triton, GPUs). |
| `/workspace/resume/experience_stories.docx` | **D7. "Career Facts":** pitches, capacity planning, misstep, Incident Response STAR. |
| `/workspace/resume/condensed_experience.docx` | Condensed role-by-role bullets. |
| `/workspace/resume/outgoing/Ram_Vellamsetti_Resume.docx` (+ variants in `/workspace/resume/`) | Current resume. |
| `/workspace/docs/Ram_Vellamsetti_Employment_History.docx` | Employment history. |
| `/workspace/learning-notes/kubernetes.md` | EndpointSlices, CRI/CNI/CSI notes. |
| `/workspace/hcdwiki/Observability.md` | OTel SDK + OTLP to Grafana Cloud conventions. |
| `/workspace/hcdwiki/Native-Services-vs-Managed-Kubernetes.md`, `Infrastructure-as-Code.md`, `/workspace/hcd/docs/runbooks/public-dns.md` | ECS Fargate vs Lambda vs EKS decision; Terraform roots; DNS runbook. |
| `/workspace/data-structures-python-samples/` | Earlier copy of the 37 samples now in `src/data-structures/`. |

Not treated as SRE docs: `/workspace/obsidian/**` (Ram's personal vault), LinkedIn routine reports, `/workspace/haureesh/**`.

---

## 3. Troubleshooting knowledge base

Each entry lists the doc steps (cited), Fargate/ECS steps (SP where not in docs) and what can be automated. The functions are in sections 4-6.

### 3.1 Workloads / pods

**OOMKilled (exit 137) / ECS `OutOfMemoryError`**
- Docs: `kubectl get pods`; `kubectl describe pod | grep -A3 "Last State"` → `Reason: OOMKilled, Exit Code: 137`; fix `kubectl set resources --requests=memory=… --limits=memory=…`; verify `kubectl top pod` [doc: D1 R1]. Raise limit, fix leak, tune heap [doc: D2 §5.2, §5.3]. 137 = SIGKILL [doc: D1 §3.1]. cgroup `memory.events oom_kill` is ground truth [doc: D1 §1.7].
- EKS Fargate (SP): pod size = max(init requests, sum of app requests) + ~256 MiB, rounded up to a Fargate size; read the `CapacityProvisioned` pod annotation and Container Insights `pod_memory_utilization`.
- ECS (SP): `stoppedReason` `OutOfMemoryError: Container killed due to memory usage`, container `exitCode 137`; compare task/container `memory`/`memoryReservation` with `MemoryUtilized`.
- Detect: yes. Auto-fix: no. Suggest new limit (p99 × 1.3); ECS may *register* a new task-def revision with `--apply` but never deploys it.

**CrashLoopBackOff / ECS "Essential container in task exited"**
- Docs: RESTARTS climbing, `describe pod | grep -A4 "Last State"`, `kubectl logs --previous` [doc: D1 A1]; causes: app error, bad config/secret, failing liveness [doc: D2 §5.2]; exit codes 1/126/127/139/143 [doc: D1 §3.1]; workflow [doc: D2 §5.1]; escalate with log evidence when a dependency is at fault and update the runbook [doc: D7 Incident Response].
- ECS (SP): service events show start/stop churn; read exit code and the `awslogs` stream. Stopped tasks are kept only ~1 hour, so capture `ECS Task State Change` via EventBridge.
- Detect: yes (exit-code class + last N log lines). Auto-fix: no (restarting doesn't fix a crash loop).

**ImagePullBackOff / ErrImagePull / ECS `CannotPullContainerError`**
- Docs: `describe pod | grep -i failed` (`not found`), fix `kubectl set image` [doc: D1 A2]; wrong tag, registry auth, rate limits, network [doc: D2 §5.2].
- EKS Fargate (SP): pulls use the Fargate profile's **pod execution role** (`ecr:GetAuthorizationToken`, `BatchGetImage`, `GetDownloadUrlForLayer`); private subnets need NAT or `ecr.api`/`ecr.dkr`/`s3` endpoints; arch mismatch → exit 126 `exec format error`.
- ECS (SP): `... not found | AccessDenied | i/o timeout` → missing tag (`ecr:DescribeImages`), task **execution role** perms, no route (no NAT/endpoint, or `assignPublicIp=DISABLED` in a public subnet).
- Detect: yes. Auto-fix: no.

**Pending / ECS PROVISIONING, placement, capacity**
- Docs: `describe pod | grep -A2 FailedScheduling` (`Insufficient cpu`, untolerated taint) [doc: D1 R2]; table: resources, taints, affinity, unbound PVC, quota [doc: D2 §5.2]; quota `FailedCreate` [doc: D1 R4]; `--field-selector=status.phase=Pending` [doc: D2 §5.4].
- EKS Fargate (SP): **profile selector mismatch** → pod keeps `schedulerName: default-scheduler` and fails with `0/0 nodes are available` (matched pods get `fargate-scheduler`); `Pod not supported on Fargate` (DaemonSet, hostNetwork, privileged, hostPort, HostPath) [doc: D8 for DaemonSet/privileged]; request > 16 vCPU / 120 GiB; profile subnets out of IPs or not private; Fargate vCPU quota.
- ECS (SP): `lastStatus` stuck `PROVISIONING`; events `unable to place a task ... Capacity is unavailable at this time` (Fargate) or `no container instance met all of its requirements` (EC2); `ResourceInitializationError`; Fargate vCPU quota `L-3032A538`.
- Detect: yes. Auto-fix: no.

**Liveness / readiness / startup probes / ECS health checks**
- Docs: READY 0/1 or restarts every 30-60s; `describe pod | grep Unhealthy` (`statuscode: 404`); EndpointSlices not ready; fix probe path/port [doc: D1 A3]; probe path/port, deps, startup [doc: D2 §5.2]; aggressive liveness → restart storms; readiness must not depend on optional deps [doc: D2 §4.2].
- Startup probe (SP): use `startupProbe` instead of large `initialDelaySeconds`.
- ECS (SP): `Task failed container health checks` / `Task failed ELB health checks in (target-group …)`; `healthCheckGracePeriodSeconds` too short; TG path/port/matcher.
- Detect: yes. Auto-fix: no.

**CreateContainerConfigError / ECS `ResourceInitializationError`**
- Docs: `configmap "app-config" not found`; create it, `kubectl rollout restart` [doc: D1 A4].
- ECS (SP): `unable to pull secrets or registry auth` → execution role lacks `secretsmanager:GetSecretValue`/`ssm:GetParameters`/`kms:Decrypt`, wrong ARN, no route to endpoints; `failed to validate logger args` → missing log group.
- Detect: yes (existence via `DescribeSecret`/`DescribeParameters`, never values). Auto-fix: no.

**Evicted / ephemeral storage**
- Docs: `exceeded its local ephemeral storage limit`; raise `ephemeral-storage` limit; delete Failed pods [doc: D1 R5]; pressure evictions bypass PDBs [doc: D1 §1.5.1].
- SP: EKS Fargate 20 GiB default (up to 175 GiB); ECS Fargate 20 GiB (up to 200 GiB), no eviction, app sees `no space left on device`.
- Detect: yes. Auto-fix: delete Failed/Evicted pod objects (doc cleanup step). Limits: suggest.

**CPU throttling** — `kubectl top`, `cpu.stat nr_throttled` [doc: D1 R3]; limits throttle, not kill [doc: D2 §5.3]. ECS (SP): `CpuUtilized` vs `CpuReserved`. Detect; suggest.

**Stuck Terminating / ECS STOPPING** — finalizers, SIGTERM ignored, node unreachable; force delete last resort [doc: D2 §5.2, §5.3]. ECS (SP): deregistration delay (300s default), `stopTimeout` (30s default, 120s max). Detect; suggest; never auto-force.

**Quota** — `get events --field-selector reason=FailedCreate`, `describe resourcequota` [doc: D1 R4]. ECS (SP): Service Quotas. Detect; suggest.

### 3.2 Cluster

- **API server / throttling.** `kubectl get --raw /readyz`; `etcdserver: request timed out` [doc: D1 C4]; apiserver 401/403/500/503/504 [doc: D1 §3.1, C3, C5]; `kubectl auth can-i` [doc: D1 C5]; on EKS control-plane problems surface as API errors/throttling [doc: D8]. SP: `eks:DescribeCluster` `status` + `health.issues`; control-plane logs (`api`, `audit`, `authenticator`, `controllerManager`, `scheduler`) in `/aws/eks/<cluster>/cluster`; 429s and `apiserver_flowcontrol_rejected_requests_total`. ECS (SP): `ThrottlingException` in CloudTrail, `AWS/Usage CallCount`.
- **etcd.** Self-managed etcd steps [doc: D1 C4]. **EKS: no etcd access.** Closest (SP): `/readyz?verbose` etcd check, `apiserver_storage_objects`/`apiserver_storage_size_bytes`, `etcdserver` errors in control-plane logs, cluster health issues. **ECS: no equivalent.**
- **Autoscaling.** HPA `FailedGetResourceMetric`, metrics-server, requests [doc: D1 C7]; CA/Karpenter for Pending [doc: D2 §4.1, §5.2]. **EKS Fargate: no CA/Karpenter for Fargate pods**; failures appear as Pending/quota/subnet (SP). ECS (SP): Application Auto Scaling activities, capacity providers (FARGATE/FARGATE_SPOT; EC2 ASG managed scaling), quotas.
- **Certificates.** `openssl x509 -noout -enddate` [doc: D1 C3]. EKS manages them; closest signal (SP): `aws eks get-token`/kubeconfig 401.

### 3.3 Nodes

- **NotReady / kubelet.** `describe node` (`Ready Unknown`), `systemctl is-active kubelet` [doc: D1 C1]; taints + 300s toleration [doc: D2 §4.1]. **EKS Fargate: no user-managed nodes/kubelet**; each pod has a `fargate-ip-*` virtual node. Closest (SP): that node's Ready condition + pod events.
- **Memory/Disk/PID pressure.** `describe node | grep -E 'DiskPressure|Taints'`, `/configz` evictionHard [doc: D1 C6]; priority-based eviction [doc: D2 §4.1]. **Fargate (EKS and ECS): not applicable**; closest = pod OOM (R1) and ephemeral eviction (R5). ECS EC2 (SP): container-instance `remainingResources`, `agentConnected`.
- **Cordon/drain blocked by PDB.** `kubectl get pdb` (ALLOWED DISRUPTIONS 0), eviction 200/429, `maxUnavailable: 1`, `unhealthyPodEvictionPolicy: AlwaysAllow` [doc: D1 §1.5.1, C2]; cordon/drain/uncordon [doc: D2 §4.2]. **Fargate: no cordon/drain**, but Fargate patching evictions honor PDBs (SP), so zero-budget PDBs still block. ECS EC2 (SP): `minimumHealthyPercent` blocks DRAINING.
- **Fargate node replacement / ECS task retirement.** (SP) EKS: AWS Health Fargate patching events; bare pods are lost. ECS: `AWS_ECS_TASK_PATCHING_RETIREMENT`, `platformVersion` (`LATEST` vs pinned). Auto-fix: early `update-service --force-new-deployment` with `--apply`.

### 3.4 Networking

- **DNS.** `nslookup` from dnsutils (timeouts), kube-dns EndpointSlices empty, scale CoreDNS [doc: D1 N1]; `ENOTFOUND`/`EAI_AGAIN` [doc: D1 §3.1]; dig first [doc: D3, D4]. EKS Fargate (SP): CoreDNS needs a kube-system profile **and** removal of `eks.amazonaws.com/compute-type: ec2`. ECS (SP): VPC `enableDnsSupport/Hostnames`, Cloud Map private zone association.
- **Service discovery.** Selector mismatch → no endpoints → `ECONNREFUSED`/curl 7 [doc: D1 N2]. ECS (SP): Cloud Map instance health, Service Connect config + Envoy logs.
- **Connectivity / policy / SGs.** curl 28 after a policy; allow the **pod** port [doc: D1 N3]; `ETIMEDOUT` → NetworkPolicy/SG/NACL [doc: D1 §3.1]. EKS Fargate (SP): **VPC CNI NetworkPolicy is not enforced on Fargate pods**; use `SecurityGroupPolicy` (default = cluster SG). ECS (SP): task ENI SGs/NACLs.
- **IPs / ENIs.** (SP) EKS Fargate: one subnet IP per pod; ENI/prefix limits n/a (EC2 `aws-node` only). ECS: `Timeout waiting for network interface provisioning to complete`, subnet IP exhaustion; EC2 ENI limits/trunking.
- **NAT / endpoints.** Registry endpoint access [doc: D2 §5.2]; (SP) `ecr.api`, `ecr.dkr`, `s3` gateway, `logs`, `secretsmanager`, `ssm`, `sts`.
- **Chain.** dig → ip route/traceroute → nc -zv → openssl s_client → curl -v → SG/iptables [doc: D3, D4]. Run inside the workload via `kubectl debug` (EKS) or ECS Exec; opt-in only.

### 3.5 Load balancing

- **5xx origin / target health.** ALB 502 (keepalive < 60s idle, pod killed mid-request), 503 (no healthy targets, readiness, LB controller/TargetGroupBinding), 504 (no response within idle timeout, SG blocks pod port, wrong port), 460/463; `aws elbv2 describe-target-health`; `HTTPCode_ELB_5XX_Count` vs `HTTPCode_Target_5XX_Count`; `elb_status_code ≠ target_status_code` [doc: D1 §3.1]; NGINX/Traefik 499/502/504 [doc: D1 §3.1]; 500 vs 504 [doc: D5 Q1].
- **Ingress / controller.** 404/503/no ADDRESS, `service port not found` [doc: D1 N4]; `<pending>` EXTERNAL-IP [doc: D1 L1]; uneven traffic/affinity [doc: D1 L2, L3]. EKS Fargate (SP): AWS LB Controller requires `target-type: ip`; IRSA role, TargetGroupBinding status, subnet tags `kubernetes.io/role/elb`.
- **Deregistration / grace.** (SP) 502s on deploy when apps exit before deregistration; EKS `preStop` sleep + readiness gates; ECS `healthCheckGracePeriodSeconds`, `deregistration_delay.timeout_seconds`, `stopTimeout`.
- **Circuit breaker / rollback.** ECS deployment circuit breaker rolls back failed deployments [doc: D5 Q8]; rollback runbooks [doc: D2 §3.6]; canary rollback [doc: D6 S7]. SP: `rolloutState FAILED`, `rolloutStateReason`, `deploymentCircuitBreaker {enable, rollback}`.

### 3.6 Timeouts

- API: boto3 5s/60s and K8s `_request_timeout=30` already in opsKit; apiserver 504 / etcd timeouts [doc: D1 C4, §3.1].
- Readiness/startup: `timeoutSeconds` default 1s (SP); aggressive probes [doc: D2 §4.2].
- LB idle: ALB 60s; app keepalive must exceed it [doc: D1 §3.1]; NLB 350s (SP).
- Upstream: NGINX `proxy_read_timeout` → 504; CPU throttling slows responses [doc: D1 §3.1, R3].
- DNS: 5s lookup timeouts [doc: D1 N1]; `ndots:5` amplification (SP).
- Layering of timeout/retry/breaker [doc: D5 Q8]; backoff with jitter [doc: D6 S8].

---

## 4. Library 1: `opskit.eks_fargate_troubleshoot` (independent)

**Description:** read-only diagnosis of EKS clusters running workloads on Fargate. For each symptom it gathers evidence (pod status, events, previous logs, Fargate profiles, control-plane health, LB controller state, target health), classifies the cause and returns a structured finding with a suggested fix. Remediation needs `--apply` and goes through `ChangeBudget`.

**Built on:** the `kubernetes` Python client (primary); `kubectl`/`eksctl` equivalents printed in every finding (`eksctl get fargateprofile` optional fallback via `subprocess` with timeout); boto3 `eks`, `logs`, `cloudwatch`, `elbv2`, `ecr`, `ec2`, `iam`, `health`. **No imports from `ecs_fargate_troubleshoot`; no shared rules engine.** Its own rule table lives in `rules.py`. (It does reuse existing opsKit core helpers below; those are generic building blocks, not a shared troubleshooting layer.)

**opsKit patterns:** `aws.client`/`create_session`/`assume_role_session`, `paginate`, `k8s.load_clients` + `_request_timeout`, `safety.ChangeBudget` + `maintenance_window`, `retry.retry`, `log.setup_logging`, `checks.Finding`/`Report` exit codes 0/1/2, `fan_out`, `from __future__ import annotations` + PEP 604, `k8s` extra, tests with mock K8s clients and moto.

### 4.1 Layout

```
src/opskit/eks_fargate_troubleshoot/
  __init__.py  __main__.py      # python -m opskit.eks_fargate_troubleshoot
  models.py                     # Evidence, Remedy, Diagnosis (own copy)
  rules.py                      # EKS-Fargate symptom -> cause -> fix table
  context.py                    # EksContext
  workloads.py                  # pods
  cluster.py  nodes.py  networking.py  loadbalancing.py  timeouts.py
  remediate.py                  # only mutating module, ChangeBudget-gated
```

```python
@dataclass
class Evidence: source: str; detail: str
@dataclass
class Remedy: summary: str; commands: list[str]; automatable: bool; doc_ref: str   # "D1 R1" or "SP"
@dataclass
class Diagnosis:
    symptom: str; resource: str; cause: str; severity: str
    evidence: list[Evidence]; remedies: list[Remedy]
    def to_finding(self) -> opskit.checks.Finding: ...
@dataclass
class EksContext:
    cluster: str; region: str; session: boto3.Session | None = None
    core: Any = None; apps: Any = None; request_timeout_s: int = 30
```

### 4.2 workloads.py

| Signature | Automates | Split |
|---|---|---|
| `diagnose_pod(ctx: EksContext, namespace: str, name: str, log_tail: int = 100) -> list[Diagnosis]` | D2 §5.1 (get, describe, events, logs --previous, lastState) | Detect |
| `diagnose_namespace(ctx: EksContext, namespace: str \| None = None, label_selector: str = "") -> list[Diagnosis]` | D2 §5.4 | Detect |
| `check_oom(ctx: EksContext, namespace: str, name: str, lookback_hours: int = 24) -> Diagnosis \| None` | D1 R1, D2 §5.2-5.3; Fargate sizing (SP) | Detect; suggest |
| `check_crashloop(ctx: EksContext, namespace: str, name: str, log_tail: int = 100) -> Diagnosis \| None` | D1 A1, §3.1 exit codes, D2 §5.2 | Detect; suggest |
| `check_image_pull(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 A2, D2 §5.2; ECR/role/endpoints/arch (SP) | Detect; suggest |
| `check_pending(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 R2/R4, D2 §5.2; profile/compat/size/IPs (SP) | Detect; suggest |
| `match_fargate_profile(ctx: EksContext, namespace: str, labels: dict[str, str]) -> str \| None` | SP | Detect |
| `check_fargate_compat(pod: Any) -> list[str]` | D8 + SP | Detect |
| `check_probes(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 A3, D2 §4.2/§5.2; startupProbe (SP) | Detect; suggest |
| `check_config_refs(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 A4 (existence by name only) | Detect; suggest |
| `check_evictions(ctx: EksContext, namespace: str \| None = None) -> list[Diagnosis]` | D1 R5, C6 | Detect; auto-fix cleanup |
| `check_cpu_throttling(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 R3 (Container Insights) | Detect; suggest |
| `check_terminating(ctx: EksContext, namespace: str \| None = None, older_than_s: int = 600) -> list[Diagnosis]` | D2 §5.2-5.3 | Detect; suggest (never force) |
| `check_quota(ctx: EksContext, namespace: str) -> list[Diagnosis]` | D1 R4 | Detect; suggest |

### 4.3 cluster.py

| Signature | Automates | Split |
|---|---|---|
| `cluster_health(ctx: EksContext) -> Diagnosis \| None` | SP: `DescribeCluster` status, health.issues, version | Detect |
| `apiserver_readiness(ctx: EksContext, verbose: bool = True) -> dict[str, str]` | D1 C4 `/readyz` | Detect |
| `etcd_signals(ctx: EksContext) -> Diagnosis \| None` | D1 C4 → **no etcd access**; readyz etcd check, storage metrics, logs (SP) | Detect |
| `apiserver_throttling(ctx: EksContext, lookback_minutes: int = 60) -> Diagnosis \| None` | D8; SP 429s/APF metrics | Detect |
| `control_plane_logging_enabled(ctx: EksContext) -> dict[str, bool]` | SP | Detect; suggest |
| `search_control_plane_logs(ctx: EksContext, pattern: str, log_type: str = "kube-apiserver", minutes: int = 60) -> list[dict]` | SP | Detect |
| `check_rbac(ctx: EksContext, verb: str, resource: str, namespace: str, as_user: str \| None = None) -> bool` | D1 C5 `auth can-i` | Detect |
| `check_hpa(ctx: EksContext, namespace: str \| None = None) -> list[Diagnosis]` | D1 C7 | Detect; suggest |
| `fargate_capacity_issues(ctx: EksContext, namespace: str \| None = None) -> list[Diagnosis]` | SP (replaces CA/Karpenter checks) | Detect |
| `addon_health(ctx: EksContext) -> list[Diagnosis]` | SP: coredns/vpc-cni/kube-proxy add-on issues | Detect |

### 4.4 nodes.py

| Signature | Automates | Split |
|---|---|---|
| `fargate_nodes(ctx: EksContext) -> list[dict]` | SP | Detect |
| `node_conditions(ctx: EksContext) -> list[Diagnosis]` | D1 C1, C6 → on Fargate returns `not_applicable` + closest signal | Detect |
| `check_pdbs(ctx: EksContext, namespace: str \| None = None) -> list[Diagnosis]` | D1 §1.5.1, C2 | Detect; suggest |
| `fargate_retirement_events(ctx: EksContext, days: int = 14) -> list[dict]` | SP | Detect |
| `bare_pods(ctx: EksContext, namespace: str \| None = None) -> list[str]` | SP | Detect; suggest |

### 4.5 networking.py

| Signature | Automates | Split |
|---|---|---|
| `check_coredns(ctx: EksContext) -> Diagnosis \| None` | D1 N1; Fargate profile + annotation (SP) | Detect; auto-fix replicas |
| `dns_probe(ctx: EksContext, namespace: str, name: str, target: str, use_ephemeral: bool = False) -> Diagnosis \| None` | D1 N1, D3/D4 | Detect, opt-in |
| `check_service_endpoints(ctx: EksContext, namespace: str, service: str) -> Diagnosis \| None` | D1 N2 | Detect; suggest |
| `check_pod_security_groups(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 N3 → SG-for-pods (SP) | Detect; suggest |
| `check_network_policies(ctx: EksContext, namespace: str) -> list[Diagnosis]` | D1 N3 (flags "not enforced on Fargate") | Detect |
| `check_subnet_ips(ctx: EksContext, min_free: int = 50) -> list[Diagnosis]` | SP | Detect |
| `check_vpc_endpoints(ctx: EksContext) -> list[Diagnosis]` | D2 §5.2 + SP | Detect |
| `connectivity_chain(ctx: EksContext, namespace: str, name: str, host: str, port: int, tls: bool = True) -> list[Evidence]` | D3/D4 | Detect, opt-in |

### 4.6 loadbalancing.py

| Signature | Automates | Split |
|---|---|---|
| `check_lb_controller(ctx: EksContext) -> Diagnosis \| None` | D1 N4/L1; controller/IRSA/webhook (SP) | Detect |
| `check_ingress(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 N4; `target-type: ip`, subnet tags (SP) | Detect; suggest |
| `check_service_lb(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 L1 | Detect |
| `target_health(ctx: EksContext, namespace: str, ingress_or_service: str) -> list[dict]` | D1 §3.1 | Detect |
| `classify_5xx(ctx: EksContext, load_balancer_arn: str, minutes: int = 60) -> Diagnosis \| None` | D1 §3.1, D5 Q1 | Detect |
| `check_deregistration(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | SP | Detect; suggest |

### 4.7 timeouts.py

| Signature | Automates | Split |
|---|---|---|
| `audit_probe_timeouts(ctx: EksContext, namespace: str \| None = None) -> list[Diagnosis]` | D2 §4.2; SP | Detect; suggest |
| `audit_lb_idle_timeout(ctx: EksContext, load_balancer_arn: str, app_keepalive_s: int \| None = None) -> Diagnosis \| None` | D1 §3.1 | Detect; suggest |
| `audit_ingress_upstream_timeouts(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 §3.1 | Detect; suggest |
| `audit_dns_config(ctx: EksContext, namespace: str, name: str) -> Diagnosis \| None` | D1 N1; SP ndots | Detect; suggest |
| `api_latency(ctx: EksContext, samples: int = 5) -> dict[str, float]` | D1 C4 | Detect |

### 4.8 remediate.py (dry-run unless `budget.apply`)

```python
def cleanup_failed_pods(ctx: EksContext, namespace: str | None, budget: ChangeBudget) -> int            # D1 R5/C6
def restore_coredns_replicas(ctx: EksContext, replicas: int, budget: ChangeBudget) -> bool              # D1 N1
def rollout_restart(ctx: EksContext, namespace: str, deployment: str, budget: ChangeBudget) -> bool     # D1 A4
def patch_service_selector(ctx: EksContext, namespace: str, service: str,
                           selector: dict[str, str], budget: ChangeBudget) -> bool                      # D1 N2, explicit opt-in
```

Suggest-only: limits, probes, images, Fargate profiles (immutable; create + delete), finalizers, force delete, PDBs, NetworkPolicy/SG.

### 4.9 CLI

```
python -m opskit.eks_fargate_troubleshoot pod <ns>/<pod> [--log-tail 100]
  ... scan [--namespace NS] [--selector k=v] [--fail-on high]     # exit 0/1/2
  ... pending <ns>/<pod> | cluster [--logs-minutes 60] | nodes
  ... dns [--probe <ns>/<pod> --target NAME] | service <ns>/<svc> | ingress <ns>/<ing>
  ... lb <alb-arn> [--minutes 60] | timeouts [--namespace NS]
  ... fix <action> ... --apply [--max-changes 5]
common: --cluster NAME --region R [--profile P] [--role-arn ARN] [--json]
```

A console-script entry in `pyproject.toml` is a follow-up (this change doesn't edit existing files).

### 4.10 Permissions

- **IAM:** `eks:DescribeCluster`, `ListFargateProfiles`, `DescribeFargateProfile`, `ListAddons`, `DescribeAddon`; `logs:FilterLogEvents`, `GetLogEvents`, `DescribeLogGroups`; `cloudwatch:GetMetricData`; `elasticloadbalancing:Describe*` (LBs, TGs, target health, attributes, listeners, rules); `ecr:DescribeImages`, `DescribeRepositories`, `DescribePullThroughCacheRules`; `ec2:DescribeSubnets`, `DescribeVpcEndpoints`, `DescribeSecurityGroups`, `DescribeSecurityGroupRules`, `DescribeRouteTables`; `iam:SimulatePrincipalPolicy`; `health:DescribeEvents`; `servicequotas:GetServiceQuota`.
- **RBAC (read ClusterRole):** get/list/watch `pods`, `pods/log`, `events`, `services`, `endpoints`, `configmaps`, `namespaces`, `nodes`, `resourcequotas`, `limitranges`, `persistentvolumeclaims`, `endpointslices`, `deployments`, `replicasets`, `statefulsets`, `daemonsets`, `ingresses`, `networkpolicies`, `poddisruptionbudgets`, `horizontalpodautoscalers`, `targetgroupbindings`, `securitygrouppolicies`; nonResourceURLs `/readyz`, `/livez`, `/metrics`. Secret existence checks are off by default (`get secrets` exposes data).
- **Opt-in:** `pods/ephemeralcontainers` patch or `pods/exec` create (probes). Remediation: `delete pods`, `patch deployments`, `deployments/scale`, `patch services`.

---

## 5. Library 2: `opskit.ecs_fargate_troubleshoot` (independent)

**Description:** read-only diagnosis of ECS services and tasks on Fargate (with EC2 launch-type branches where they differ). It reads service events, deployments, stopped tasks and `stoppedReason`, container exit codes, CloudWatch Logs, target health, Cloud Map / Service Connect, ENI/subnet/endpoint state and quotas, then classifies each failure and suggests a fix. Remediation needs `--apply` + `ChangeBudget`.

**Built on:** boto3 `ecs`, `logs`, `elbv2`, `cloudwatch`, `ec2`, `ecr`, `servicediscovery`, `application-autoscaling`, `service-quotas`, `iam`, `health`, `cloudtrail`; each finding also prints the matching `aws ecs ...` CLI command. **No imports from `eks_fargate_troubleshoot`; no `kubernetes` dependency; no shared rules engine.**

**opsKit patterns:** same core helpers as section 4 (`aws.client`, `paginate`, `fan_out`/`enabled_regions`, `ChangeBudget`, `retry`, `checks` exit codes, JSON logging), plus moto tests (`mock_aws` covers ecs/elbv2/logs/ec2).

### 5.1 Layout and models

Same layout as 4.1 under `src/opskit/ecs_fargate_troubleshoot/`, with its own `models.py` and `rules.py`.

```python
@dataclass
class EcsContext:
    cluster: str; region: str; session: boto3.Session | None = None
    stopped_lookback: int = 50          # stopped tasks are retained only ~1 hour
```

### 5.2 workloads.py (services and tasks)

| Signature | Automates | Split |
|---|---|---|
| `diagnose_service(ctx: EcsContext, service: str) -> list[Diagnosis]` | D2 §5.1 adapted: events, deployments, stopped tasks, logs (SP) | Detect |
| `diagnose_task(ctx: EcsContext, task_arn: str, log_tail: int = 100) -> list[Diagnosis]` | SP | Detect |
| `recent_stopped_tasks(ctx: EcsContext, service: str, limit: int = 50) -> list[dict]` | SP | Detect |
| `parse_stopped_reason(reason: str) -> tuple[str, str]` | SP (pattern → category, rule id) | Detect |
| `check_oom(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 R1, D2 §5.3 + SP | Detect; suggest / opt-in register |
| `check_essential_exit(ctx: EcsContext, service: str, log_tail: int = 100) -> Diagnosis \| None` | D1 A1, §3.1; D7 | Detect; suggest |
| `check_restart_loop(ctx: EcsContext, service: str, window_minutes: int = 30) -> Diagnosis \| None` | D1 A1 analog (SP) | Detect |
| `check_image_pull(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 A2, D2 §5.2 + SP | Detect; suggest |
| `check_resource_init(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 A4 analog (SP) | Detect; suggest |
| `check_container_health(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 A3, D2 §4.2 + SP | Detect; suggest |
| `check_stuck_provisioning(ctx: EcsContext, service: str, older_than_s: int = 300) -> Diagnosis \| None` | D1 R2 analog (SP) | Detect |
| `check_cpu_saturation(ctx: EcsContext, service: str, minutes: int = 60) -> Diagnosis \| None` | D1 R3 analog | Detect; suggest |
| `check_ephemeral_storage(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 R5 analog (SP) | Detect; suggest |
| `check_stuck_stopping(ctx: EcsContext, service: str) -> Diagnosis \| None` | D2 §5.2 Terminating analog (SP) | Detect; suggest |

### 5.3 cluster.py

| Signature | Automates | Split |
|---|---|---|
| `cluster_health(ctx: EcsContext) -> Diagnosis \| None` | SP: `DescribeClusters` status, counts, settings | Detect |
| `check_capacity_providers(ctx: EcsContext, service: str \| None = None) -> list[Diagnosis]` | SP | Detect; suggest |
| `check_placement_failures(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 R2 analog | Detect |
| `check_service_quotas(ctx: EcsContext) -> list[Diagnosis]` | D1 R4 analog | Detect; suggest |
| `api_throttling(ctx: EcsContext, minutes: int = 60) -> Diagnosis \| None` | D8 analog (SP) | Detect |
| `check_service_autoscaling(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 C7 analog | Detect; suggest |
| `control_plane_note() -> Diagnosis` | D1 C1/C4 → **not applicable: ECS control plane is fully managed, no etcd/apiserver**; closest = API errors/throttling, AWS Health | Detect |

### 5.4 nodes.py

| Signature | Automates | Split |
|---|---|---|
| `nodes_not_applicable() -> Diagnosis` | D1 C1/C6 → **Fargate: no nodes**; closest = task stop reasons, retirement events, platform version | Detect |
| `check_platform_versions(ctx: EcsContext, service: str \| None = None) -> list[Diagnosis]` | SP | Detect; suggest |
| `task_retirement_events(ctx: EcsContext, days: int = 14) -> list[dict]` | SP | Detect; auto-fix (redeploy early) |
| `check_container_instances(ctx: EcsContext) -> list[Diagnosis]` | **EC2 launch type only**: D1 C1/C6 analog | Detect |
| `check_draining_blocked(ctx: EcsContext) -> list[Diagnosis]` | **EC2 only**: D1 C2 analog | Detect; suggest |

### 5.5 networking.py

| Signature | Automates | Split |
|---|---|---|
| `check_eni_provisioning(ctx: EcsContext, service: str) -> Diagnosis \| None` | SP | Detect |
| `check_subnet_ips(ctx: EcsContext, service: str, min_free: int = 50) -> list[Diagnosis]` | SP | Detect |
| `check_security_groups(ctx: EcsContext, service: str) -> list[Diagnosis]` | D1 N3 analog | Detect; suggest |
| `check_egress_path(ctx: EcsContext, service: str) -> Diagnosis \| None` | D2 §5.2 + SP (NAT / public IP / endpoints) | Detect; suggest |
| `check_service_discovery(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 N2 analog (Cloud Map) | Detect |
| `check_service_connect(ctx: EcsContext, service: str) -> Diagnosis \| None` | SP | Detect |
| `check_vpc_dns(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 N1 analog | Detect; suggest |
| `connectivity_chain(ctx: EcsContext, task_arn: str, container: str, host: str, port: int, tls: bool = True) -> list[Evidence]` | D3/D4 via ECS Exec, opt-in | Detect |

### 5.6 loadbalancing.py

| Signature | Automates | Split |
|---|---|---|
| `target_health(ctx: EcsContext, service: str) -> list[dict]` | D1 §3.1 | Detect |
| `check_health_check_config(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 A3 analog + SP grace period | Detect; suggest |
| `classify_5xx(ctx: EcsContext, service: str, minutes: int = 60) -> Diagnosis \| None` | D1 §3.1, D5 Q1 | Detect |
| `check_deregistration(ctx: EcsContext, service: str) -> Diagnosis \| None` | SP | Detect; suggest |
| `check_deployments(ctx: EcsContext, service: str) -> Diagnosis \| None` | D5 Q8, D2 §3.6 | Detect |

### 5.7 timeouts.py

| Signature | Automates | Split |
|---|---|---|
| `audit_health_check_timeouts(ctx: EcsContext, service: str) -> list[Diagnosis]` | D2 §4.2 + SP | Detect; suggest |
| `audit_lb_idle_timeout(ctx: EcsContext, service: str, app_keepalive_s: int \| None = None) -> Diagnosis \| None` | D1 §3.1 | Detect; suggest |
| `audit_stop_timeout(ctx: EcsContext, service: str) -> Diagnosis \| None` | SP | Detect; suggest |
| `audit_upstream_timeouts(ctx: EcsContext, service: str) -> Diagnosis \| None` | D1 §3.1 (Service Connect timeouts) | Detect; suggest |
| `api_latency(ctx: EcsContext, samples: int = 5) -> dict[str, float]` | SP | Detect |

### 5.8 remediate.py (dry-run unless `budget.apply`)

```python
def force_new_deployment(ctx: EcsContext, service: str, budget: ChangeBudget) -> bool                  # retirement, stale tasks
def rollback_to_previous(ctx: EcsContext, service: str, budget: ChangeBudget) -> str | None            # D5 Q8, D2 §3.6
def register_task_def_with_memory(ctx: EcsContext, family: str, container: str,
                                  memory_mib: int, budget: ChangeBudget) -> str | None                 # registers only, no deploy
def enable_circuit_breaker(ctx: EcsContext, service: str, budget: ChangeBudget) -> bool               # D5 Q8
```

Suggest-only: SG/NACL changes, IAM role policies, subnets, health-check paths, quotas, `stopTimeout`, capacity providers.

### 5.9 CLI and permissions

```
python -m opskit.ecs_fargate_troubleshoot service <svc> | task <arn> | scan [--fail-on high]
  ... cluster | nodes | network <svc> | lb <svc> | timeouts <svc> | fix <action> ... --apply [--max-changes 5]
common: --cluster NAME --region R [--profile P] [--role-arn ARN] [--json]
```

- **IAM (read):** `ecs:Describe*`, `ecs:List*`; `logs:FilterLogEvents`, `GetLogEvents`, `DescribeLogGroups`; `elasticloadbalancing:Describe*`; `cloudwatch:GetMetricData`; `ec2:DescribeSubnets`, `DescribeNetworkInterfaces`, `DescribeSecurityGroups`, `DescribeSecurityGroupRules`, `DescribeRouteTables`, `DescribeVpcEndpoints`, `DescribeVpcAttribute`, `DescribeNatGateways`; `ecr:DescribeImages`; `servicediscovery:Get*`/`List*`; `application-autoscaling:Describe*`; `servicequotas:GetServiceQuota`; `iam:SimulatePrincipalPolicy`; `secretsmanager:DescribeSecret`, `ssm:DescribeParameters` (**never** `GetSecretValue`); `health:DescribeEvents`; `cloudtrail:LookupEvents`.
- **Opt-in:** `ecs:ExecuteCommand` + `ssmmessages:*` (connectivity chain). Remediation: `ecs:UpdateService`, `ecs:RegisterTaskDefinition`, `iam:PassRole` (task/execution roles only).

---

## 6. Side-by-side error mapping (EKS Fargate vs ECS Fargate)

The two libraries are independent; this table only shows how each maps the same symptom. **N/A** means the concept doesn't exist on that platform, and the closest diagnosable signal is given.

| # | Area | Symptom | Docs | EKS Fargate signal → `eks_fargate_troubleshoot` | ECS Fargate signal → `ecs_fargate_troubleshoot` | Auto-fix |
|---|---|---|---|---|---|---|
| 1 | Workloads | Out of memory | D1 R1, D2 §5.3 | `OOMKilled`, exit 137, `CapacityProvisioned` → `workloads.check_oom` | `OutOfMemoryError`, exit 137 → `workloads.check_oom` | ECS: register task-def only |
| 2 | Workloads | App crash / restart loop | D1 A1, §3.1, D7 | `CrashLoopBackOff`, `logs --previous` → `check_crashloop` | `Essential container in task exited` → `check_essential_exit`, `check_restart_loop` | No |
| 3 | Workloads | Image pull | D1 A2, D2 §5.2 | `ImagePullBackOff`, pod execution role → `check_image_pull` | `CannotPullContainerError`, task execution role → `check_image_pull` | No |
| 4 | Workloads | Wrong architecture | D1 §3.1 (126) | exit 126 `exec format error` → `check_crashloop` | exit 126 / `runtimePlatform` mismatch → `check_essential_exit` | No |
| 5 | Workloads | Not scheduled / not placed | D1 R2, D2 §5.2 | Pending, `0/0 nodes`, `default-scheduler` → `check_pending`, `match_fargate_profile` | `PROVISIONING`, `unable to place a task` → `check_stuck_provisioning`, `cluster.check_placement_failures` | No |
| 6 | Workloads | Unsupported spec | D8 | DaemonSet/privileged/hostNetwork → `check_fargate_compat` | `privileged`, `host` network invalid on Fargate → `RegisterTaskDefinition` error (SP), `diagnose_service` | No |
| 7 | Workloads | Liveness / health failures | D1 A3, D2 §4.2 | `Unhealthy` liveness events → `check_probes` | `Task failed container health checks` → `check_container_health` | No |
| 8 | Workloads | Not ready / no traffic | D1 A3 | readiness failing, endpoints not ready → `check_probes` | target `unhealthy`/`initial` → `loadbalancing.target_health` | No |
| 9 | Workloads | Config / secret missing | D1 A4 | `CreateContainerConfigError` → `check_config_refs` | `ResourceInitializationError: unable to pull secrets` → `check_resource_init` | EKS: rollout restart after fix |
| 10 | Workloads | Logging misconfigured | SP | Fluent Bit `aws-logging` ConfigMap missing → `check_config_refs` | `failed to validate logger args` → `check_resource_init` | No |
| 11 | Workloads | Ephemeral storage | D1 R5 | `Evicted ... ephemeral storage` → `check_evictions` | `no space left on device` (no eviction) → `check_ephemeral_storage` | EKS: delete Failed pods |
| 12 | Workloads | CPU throttling / saturation | D1 R3 | Container Insights CPU vs limit → `check_cpu_throttling` | `CpuUtilized` vs `CpuReserved` → `check_cpu_saturation` | No |
| 13 | Workloads | Stuck terminating / stopping | D2 §5.2-5.3 | finalizers, grace → `check_terminating` | `STOPPING`, dereg delay, `stopTimeout` → `check_stuck_stopping` | No (never force) |
| 14 | Workloads | Quota exceeded | D1 R4 | `ResourceQuota` `FailedCreate` → `check_quota` | Service Quotas (tasks, vCPU `L-3032A538`) → `cluster.check_service_quotas` | No |
| 15 | Cluster | Control plane health | D1 C4, D8 | `DescribeCluster` health + `/readyz` → `cluster.cluster_health`, `apiserver_readiness` | **N/A** (managed); closest: API errors, AWS Health → `cluster.control_plane_note` | No |
| 16 | Cluster | etcd | D1 C4 | **N/A** (no etcd access); closest: readyz etcd, storage metrics, logs → `cluster.etcd_signals` | **N/A** (no equivalent) → `control_plane_note` | No |
| 17 | Cluster | API throttling | D8 | 429, APF metrics → `cluster.apiserver_throttling` | `ThrottlingException` (CloudTrail) → `cluster.api_throttling` | No |
| 18 | Cluster | Control-plane logs | SP | `/aws/eks/<c>/cluster` → `control_plane_logging_enabled`, `search_control_plane_logs` | **N/A**; closest: CloudTrail + service events → `diagnose_service` | No |
| 19 | Cluster | Authorization | D1 C5 | 401/403, `auth can-i`, access entries → `cluster.check_rbac` | `AccessDenied` in stop reasons / CloudTrail, `iam:SimulatePrincipalPolicy` → `check_image_pull`, `check_resource_init` | No |
| 20 | Cluster | Autoscaling | D1 C7, D2 §4.1 | HPA metrics → `cluster.check_hpa`; CA/Karpenter **N/A** for Fargate → `fargate_capacity_issues` | App Auto Scaling activities → `cluster.check_service_autoscaling` | No |
| 21 | Cluster | Capacity | D2 §5.2 | Fargate vCPU quota, profile subnets → `fargate_capacity_issues` | `Capacity is unavailable`, FARGATE_SPOT → `check_capacity_providers` | No |
| 22 | Cluster | Add-ons / agents | SP | coredns/kube-proxy/vpc-cni add-on health → `cluster.addon_health` | **N/A** on Fargate; EC2 `agentConnected` → `nodes.check_container_instances` | No |
| 23 | Cluster | Certificates | D1 C3 | managed; closest: kubeconfig/token 401 → `check_rbac` | **N/A** | No |
| 24 | Nodes | Node NotReady / kubelet | D1 C1, D2 §4.1 | **N/A** (virtual `fargate-ip-*` nodes) → `nodes.node_conditions`, `fargate_nodes` | **N/A** on Fargate → `nodes.nodes_not_applicable`; EC2 → `check_container_instances` | No |
| 25 | Nodes | Memory/disk/PID pressure | D1 C6 | **N/A**; closest #1, #11 → `node_conditions` | **N/A**; closest #1, #11; EC2 `remainingResources` | No |
| 26 | Nodes | Drain blocked | D1 §1.5.1, C2 | no drain, but patching honors PDBs → `nodes.check_pdbs` | **N/A** on Fargate; EC2 DRAINING vs `minimumHealthyPercent` → `check_draining_blocked` | No |
| 27 | Nodes | Host retirement / patching | SP | Fargate patching events, bare pods → `fargate_retirement_events`, `bare_pods` | `AWS_ECS_TASK_PATCHING_RETIREMENT` → `task_retirement_events` | ECS: force new deployment |
| 28 | Nodes | Runtime version | SP | Fargate platform managed by EKS version → `cluster_health` | `platformVersion` pin vs LATEST → `check_platform_versions` | No |
| 29 | Networking | DNS resolution | D1 N1, D3/D4 | CoreDNS on Fargate + annotation → `networking.check_coredns`, `dns_probe` | VPC DNS attrs, Cloud Map zone → `networking.check_vpc_dns` | EKS: CoreDNS replicas |
| 30 | Networking | Service discovery / no endpoints | D1 N2 | selector mismatch, empty EndpointSlices → `check_service_endpoints` | Cloud Map unhealthy / Service Connect → `check_service_discovery`, `check_service_connect` | EKS: selector patch (opt-in) |
| 31 | Networking | Blocked traffic | D1 N3, §3.1 | SG for pods; NetworkPolicy **not enforced** → `check_pod_security_groups`, `check_network_policies` | task ENI SGs/NACLs → `check_security_groups` | No |
| 32 | Networking | IP / ENI exhaustion | SP | profile subnet free IPs → `check_subnet_ips` | `Timeout waiting for network interface` → `check_eni_provisioning`, `check_subnet_ips` | No |
| 33 | Networking | Egress / endpoints | D2 §5.2 | NAT, `ecr`/`s3`/`logs`/`sts` endpoints → `check_vpc_endpoints` | NAT / public IP / endpoints → `check_egress_path` | No |
| 34 | Networking | End-to-end chain | D3, D4 | `kubectl debug` dig→nc→openssl→curl → `connectivity_chain` (opt-in) | ECS Exec chain → `connectivity_chain` (opt-in) | No |
| 35 | Load balancing | 5xx origin | D1 §3.1, D5 Q1 | ELB vs target 5xx → `loadbalancing.classify_5xx` | same → `loadbalancing.classify_5xx` | No |
| 36 | Load balancing | Unhealthy targets | D1 §3.1, A3 | TargetGroupBinding + target health → `target_health` | `Task failed ELB health checks` → `target_health`, `check_health_check_config` | No |
| 37 | Load balancing | LB not created | D1 N4, L1 | controller/IRSA/subnet tags/`target-type: ip` → `check_lb_controller`, `check_ingress`, `check_service_lb` | **N/A** (LB attached via service `loadBalancers`); closest: service events → `check_health_check_config` | No |
| 38 | Load balancing | 502 during deploys | D1 §3.1 | `preStop`, readiness gates, dereg → `check_deregistration` | grace period, dereg delay, `stopTimeout` → `check_deregistration` | No |
| 39 | Load balancing | Failed rollout | D5 Q8, D2 §3.6, D6 S7 | `rollout status` / ProgressDeadlineExceeded → `diagnose_namespace` | circuit breaker `rolloutState FAILED` → `check_deployments` | ECS: rollback / enable breaker |
| 40 | Timeouts | Probe / health-check timeouts | D2 §4.2 | `timeoutSeconds`, startupProbe → `timeouts.audit_probe_timeouts` | container + TG health check timing → `timeouts.audit_health_check_timeouts` | No |
| 41 | Timeouts | Idle / keepalive (502/504) | D1 §3.1 | ALB idle vs app keepalive → `audit_lb_idle_timeout`; ingress upstream → `audit_ingress_upstream_timeouts` | same → `audit_lb_idle_timeout`; Service Connect → `audit_upstream_timeouts` | No |
| 42 | Timeouts | Shutdown / DNS / API latency | D1 N1, C4 | `audit_dns_config`, `api_latency` | `audit_stop_timeout`, `api_latency` | No |

---

## 7. opsKit inventory (as of commit `b42a3e1`)

| Module | Contents |
|---|---|
| `opskit/safety.py` | `ChangeBudget` (dry-run unless `apply`, `max_changes` raises `BlastRadiusExceeded`), `is_protected(tags)`, `maintenance_window(name)` context manager |
| `opskit/retry.py` | `is_transient`, `backoff_delays` (full jitter), `@retry(attempts, base, cap)` |
| `opskit/aws.py` | `DEFAULT_CONFIG` (adaptive retries ×10, connect 5s, read 60s), `create_session`, `client`, `assume_role_session`, `paginate`, `tags_to_dict`, `age_days`, `enabled_regions`, `fan_out` |
| `opskit/checks.py` | `@check` registry, `Finding`, `Report` (exit codes 0/1/2), `run_checks` |
| `opskit/log.py` | `JsonFormatter` with secret redaction, `setup_logging` |
| `opskit/http.py` | `TimeoutSession`, `build_session` (urllib3 retries) |
| `opskit/metrics.py` | `job_metrics` (Prometheus Pushgateway) |
| `opskit/notify.py` | `notify` (webhook from env) |
| `opskit/k8s.py` | `load_clients`, `list_namespaces`/`list_pods`/`list_events`/`get_pod_logs` (with `_request_timeout`), `rollout_restart`, `wait_for_rollout`, `unhealthy_pods` |
| `opskit/inventory.py` | multi-region AWS inventory with Terraform tag metadata; JSON and Excel writers |
| `opskit/resource_insights.py` | resource health, child-resource counts, basic CloudWatch metrics |
| `opskit/aws_lambda.py` | `build_deployment_package`, `update_runtime`, `update_code` (both `ChangeBudget`-gated) |
| `opskit/api.py` | FastAPI: health, AWS inventory/insights, K8s namespaces/pods/events/unhealthy/logs/rollout |
| `opskit/clients/` | re-export shims `aws.py`, `inventory.py` and a duplicated `resource_insights.py` (see §12) |
| `opsclient/` | `opsclient` CLI (only `[project.scripts]` entry) calling the REST API |
| `examples/` | `aws_checks.py`, `ebs_cleanup.py` |
| `src/data-structures/` | 37 interview/SRE samples from D6 + `wrappers.py`, tests, pattern analyzer |
| `tests/` | 36 tests (api, aws+checks, lambda, inventory, k8s, retry, safety) all passing; plus 15 in `src/data-structures/tests` |
| Packaging | `pyproject.toml` src-layout, Python ≥3.10, extras `k8s`, `api`, `metrics`, `excel`, `dev` |

## 8. AWS Lambda findings

- **What exists:** `aws_lambda.py` only covers packaging and two deploy calls. `build_deployment_package` copies the source, pip-installs requirements into the ZIP root (600s timeout) and skips `__pycache__`/`.pyc`. `update_runtime` and `update_code` are dry-run unless `ChangeBudget(apply=True)`. Tests use a fake client.
- **Gaps:** no waiter for `LastUpdateStatus` (an `update_code` straight after `update_runtime` will hit `ResourceConflictException`); no alias/version shifting or rollback; no `Architectures`, layers or container images; no 50 MB direct-upload/S3 check; no size limit check (250 MB unzipped); no inventory of deprecated runtimes; no concurrency/throttle/error/DLQ diagnosis; no CLI.
- **Proposed `opskit.lambda_ops`:** `wait_until_updated`, `deprecated_runtimes(regions)` (fan_out), `shift_alias(function, version, weight, budget)` + auto-rollback on CloudWatch alarm, `diagnose_function` (Errors, Throttles, Duration vs timeout, `ConcurrentExecutions` vs reserved, `IteratorAge`, DLQ/on-failure destinations, init errors from logs), `s3_upload_if_large`. Motivated by D5 (rollback/MTTR), D6 S7/S8 (rollback, retry), D2 §3.6.

## 9. Shared opsKit patterns new code should follow

1. Dry-run by default; mutations only via `ChangeBudget.approve()` with `--apply` and `--max-changes`.
2. Idempotent operations; respect `is_protected` tags; run mutations inside `maintenance_window`.
3. Every AWS call through `aws.client` (timeouts + adaptive retries) and `paginate`; every K8s call with `_request_timeout`; `@retry` only for `is_transient` errors.
4. Multi-account/region via `assume_role_session`, `enabled_regions`, `fan_out`.
5. Output `Finding`/`Report` JSON, JSON logs via `setup_logging`, exit codes 0 OK / 1 findings / 2 error.
6. `from __future__ import annotations`, PEP 604 types, dataclasses; optional deps as extras; moto/fake-client tests.

## 10. Other proposed libraries (each grounded in a doc)

| Library | One line | Motivating doc |
|---|---|---|
| `aws_sqs` | Queue depth/age, DLQ redrive (gated), visibility-timeout vs consumer duration audit | D6 S3 (backpressure/DLQ) |
| `aws_sns` | Delivery-failure metrics, subscription/DLQ and policy audit | D6 S3 |
| `lambda_ops` | See §8 | D5, D6 S7/S8 |
| `aws_iam` | Unused roles/keys, policy simulation, access-denied explainer from CloudTrail | D1 C5, D3 |
| `aws_cloudwatch` | Alarm hygiene (no actions, INSUFFICIENT_DATA), Logs Insights runner, metric math helpers | D5 MTTD, D2 observability |
| `aws_stepfunctions` | Failed/timed-out executions, failed-state extraction, redrive (gated) | D6 S1 (job scheduling) |
| `aws_eventbridge` | Rule/target failure metrics, DLQ, archive replay (gated) | D6 S3 |
| `aws_s3` | Public-access/encryption/lifecycle/versioning audit, cost of incomplete multipart uploads | D3, D4 |
| `aws_secrets` | Rotation status, unused secrets, never reads values | D1 A4 |
| `ecs_eks_ops` | Inventory and version drift across clusters (EKS version/add-ons, ECS platform versions) | D2 §6, D8 |
| `aws_cost` | Idle resources (extends `examples/ebs_cleanup.py`), Cost Explorer anomalies | D3 capacity, D7 capacity planning |
| `k8s_ops` | Generic (non-Fargate) K8s triage: node pressure, PDB, drain, cert expiry | D1 C1-C7, D2 §4 |
| `otel` | OTel SDK/OTLP bootstrap matching hcdwiki conventions | `hcdwiki/Observability.md` |
| `terraform_ops` | `plan` JSON drift summarizer, state lock detection | `hcdwiki/Infrastructure-as-Code.md` |
| `linux_triage` | Host checks: df -h/-i, lsof +L1, load/PSI, OOM in dmesg, systemd failures | D3, D4, D1 §1.7 |
| `net_diag` | dig → traceroute → nc → openssl → curl chain with structured results | D3, D4 |
| `tls_check` | Certificate expiry/chain/SAN checks for endpoints and K8s secrets | D1 C3 |
| `slo` | Multi-window burn-rate calculation and alerts | D5 SLO/error budget, D6 P13 |
| `traffic_shift` | Blue-green / canary switch with automatic rollback (ALB weights, Lambda aliases, K8s Service selector) | D2 §3.2/§3.6, D6 S7 |
| `rate_limit` | Token-bucket / sliding-window limiter for ops scripts hitting APIs | D6 P10 |

## 11. Priority order

1. `ecs_fargate_troubleshoot` (largest ECS gap; everything is SP today)
2. `eks_fargate_troubleshoot`
3. `aws_cloudwatch` (feeds both libraries and `slo`)
4. `lambda_ops`
5. `slo` and `traffic_shift`
6. `net_diag`, `linux_triage`, `tls_check`
7. The remaining AWS service libraries, then `otel`, `terraform_ops`, `rate_limit`

## 12. Issues found in existing code (not fixed here, since this change adds only this file)

- `src/opskit/clients/aws.py` and `inventory.py` are thin re-export shims, but `clients/resource_insights.py` is a full copy of `opskit/resource_insights.py`, so the two can drift.
- README imports `from opsclient.resource_insights import ...`, a module that doesn't exist (it lives at `opskit.resource_insights`).
- `k8s.rollout_restart` and the API's rollout endpoint mutate with no `ChangeBudget`/dry-run, and the API has no auth.
- `k8s.unhealthy_pods` and `rollout_restart` don't pass `_request_timeout`.
- `aws.enabled_regions` takes no `session` argument and always queries with the default credentials, so it can't follow `assume_role_session`; its `service` parameter is unused.
- `aws_lambda` has no `function_updated` waiter between updates (see §8).
- `.DS_Store` and `__pycache__/*.pyc` are tracked; there's no root `.gitignore` and no CI workflow.
- New CLIs should get `[project.scripts]` entries and a `moto[ecs,elbv2,logs]` dev extra in a follow-up.
