import React, { useCallback, useEffect, useMemo, useState } from "react";

const API = "/api/cloud-container-migration";

async function apiPost(path, body) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    const error = data.error || {};
    const detail = [
      error.code && `Code: ${error.code}`,
      error.operation && `Operation: ${error.operation}`,
      error.message,
      error.remediation && `Suggested action: ${error.remediation}`,
    ].filter(Boolean).join("\n");
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

function StatusPill({ status }) {
  const colors = {
    ready: "#dcfce7", reused: "#dcfce7", created: "#dbeafe",
    partial: "#fef3c7", missing: "#ffedd5", unknown: "#fee2e2",
    failed: "#fee2e2", succeeded: "#dcfce7", running: "#dbeafe",
    queued: "#f3f4f6", blocked: "#fee2e2",
  };
  return <span style={{
    background: colors[String(status || "").toLowerCase()] || "#f3f4f6",
    borderRadius: 999, padding: "3px 9px", fontSize: 12, fontWeight: 600,
    display: "inline-block", whiteSpace: "nowrap"
  }}>{status || "unknown"}</span>;
}

function ErrorPanel({ error }) {
  if (!error) return null;
  return <div role="alert" style={{ border: "1px solid #fca5a5", background: "#fef2f2", borderRadius: 8, padding: 12, whiteSpace: "pre-wrap" }}>
    <strong>AWS operation needs attention</strong>
    <div style={{ marginTop: 6 }}>{error.message || String(error)}</div>
    {error.code && <div><strong>Error code:</strong> {error.code}</div>}
    {error.operation && <div><strong>Operation:</strong> {error.operation}</div>}
    {error.request_id && <div><strong>Request ID:</strong> {error.request_id}</div>}
    {error.remediation && <div style={{ marginTop: 6 }}><strong>Next step:</strong> {error.remediation}</div>}
  </div>;
}

const fieldStyle = { width: "100%", boxSizing: "border-box", padding: "9px 10px", border: "1px solid #d1d5db", borderRadius: 6 };
const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

export default function CloudContainerMigration({ sourceConnectionId }) {
  const [region, setRegion] = useState("ap-south-1");
  const [containerId, setContainerId] = useState("");
  const [runtime, setRuntime] = useState("auto");
  const [containers, setContainers] = useState([]);
  const [report, setReport] = useState(null);
  const [prepared, setPrepared] = useState(null);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [networkError, setNetworkError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [repositoryName, setRepositoryName] = useState("atm-migrated-apps");
  const [clusterName, setClusterName] = useState("atm-migration-cluster");
  const [serviceName, setServiceName] = useState("atm-migrated-service");
  const [executionRoleArn, setExecutionRoleArn] = useState("");
  const [logGroup, setLogGroup] = useState("/ecs/atm-migration");
  const [cpu, setCpu] = useState("256");
  const [memory, setMemory] = useState("512");
  const [containerPort, setContainerPort] = useState("");
  const [desiredCount, setDesiredCount] = useState("1");
  const [assignPublicIp, setAssignPublicIp] = useState(true);
  const [healthCheckCommand, setHealthCheckCommand] = useState("");

  const memoryOptions = useMemo(() => ({
    "256": ["512", "1024", "2048"],
    "512": ["1024", "2048", "3072", "4096"],
    "1024": ["2048", "3072", "4096", "5120", "6144", "7168", "8192"],
    "2048": Array.from({ length: 13 }, (_, i) => String(4096 + i * 1024)),
    "4096": Array.from({ length: 23 }, (_, i) => String(8192 + i * 1024)),
    "8192": Array.from({ length: 12 }, (_, i) => String(16384 + i * 4096)),
    "16384": Array.from({ length: 12 }, (_, i) => String(32768 + i * 8192)),
  }[cpu] || ["512"]), [cpu]);

  const inspect = useCallback(async () => {
    setBusy("inspect"); setError(null); setReport(null); setPrepared(null);
    try {
      const data = await apiPost("/inspect", { region });
      setReport(data.report);
      const role = data.report?.resources?.executionRole;
      if (role?.arn) setExecutionRoleArn(role.arn);
    } catch (e) {
      setError({ message: e.message });
    } finally { setBusy(""); }
  }, [region]);

  const discoverContainers = useCallback(async () => {
    if (!sourceConnectionId) {
      setNetworkError({ message: "Missing sourceConnectionId. Pass the existing ATM saved source connection ID to this component." });
      return;
    }
    setBusy("containers"); setNetworkError(null); setContainers([]);
    try {
      const data = await apiPost("/containers", { sourceConnectionId, runtime });
      setContainers(data.containers || []);
      if (data.runtime) setRuntime(data.runtime);
      if (data.containers?.length && !containerId) setContainerId(data.containers[0].id);
      if (!data.containers?.length) setNetworkError({ message: "No containers were found on the source VM." });
    } catch (e) { setNetworkError({ message: e.message }); }
    finally { setBusy(""); }
  }, [sourceConnectionId, runtime, containerId]);

  const prepare = useCallback(async () => {
    setBusy("prepare"); setError(null); setPrepared(null);
    try {
      const data = await apiPost("/prepare", {
        region, repositoryName, clusterName, logGroup,
        executionRoleName: "ecsTaskExecutionRole",
        containerPort: containerPort ? Number(containerPort) : undefined,
      });
      setPrepared(data.resources);
      if (data.resources?.executionRoleArn) setExecutionRoleArn(data.resources.executionRoleArn);
      setReport(prev => prev ? {
        ...prev,
        resources: { ...prev.resources, network: { status: "ready", message: "Infrastructure preparation completed." } }
      } : prev);
      if (data.warnings?.length) setNetworkError({ message: data.warnings.join("\n") });
    } catch (e) { setError({ message: e.message }); }
    finally { setBusy(""); }
  }, [region, repositoryName, clusterName, logGroup, containerPort]);

  const startMigration = useCallback(async () => {
    if (!sourceConnectionId) return setError({ message: "Missing sourceConnectionId." });
    if (!containerId) return setError({ message: "Select a source container first." });
    setBusy("migrate"); setError(null); setJob(null);
    try {
      const data = await apiPost("/jobs", {
        sourceConnectionId, containerId, region, repositoryName, clusterName, serviceName,
        executionRoleArn: executionRoleArn || undefined, logGroup,
        cpu, memory, containerPort: containerPort ? Number(containerPort) : undefined,
        desiredCount: Number(desiredCount), assignPublicIp,
        healthCheckCommand: healthCheckCommand || undefined,
        architecture: "X86_64",
      });
      setJob(data.job);
    } catch (e) { setError({ message: e.message }); }
    finally { setBusy(""); }
  }, [sourceConnectionId, containerId, region, repositoryName, clusterName, serviceName,
      executionRoleArn, logGroup, cpu, memory, containerPort, desiredCount, assignPublicIp, healthCheckCommand]);

  const cancel = useCallback(async () => {
    if (!job?.jobId) return;
    setBusy("cancel");
    try { await apiPost(`/jobs/${job.jobId}/cancel`, {}); }
    catch (e) { setError({ message: e.message }); }
    finally { setBusy(""); }
  }, [job]);

  useEffect(() => {
    if (!job?.jobId || ["succeeded", "failed", "cancelled"].includes(job.status)) return undefined;
    let stopped = false;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${API}/jobs/${job.jobId}`, { credentials: "same-origin" });
        const data = await response.json();
        if (!stopped && response.ok && data.ok) setJob(data.job);
      } catch (_) { /* A transient poll error should not reset the job. */ }
    }, 3000);
    return () => { stopped = true; clearInterval(timer); };
  }, [job?.jobId, job?.status]);

  const actions = report?.checks || [];
  const resources = report?.resources || {};

  return <div style={{ display: "grid", gap: 18, maxWidth: 1050, margin: "0 auto", padding: 16 }}>
    <header>
      <h2 style={{ margin: 0 }}>ATM 路 VM Container to AWS ECS</h2>
      <p style={{ color: "#4b5563", marginTop: 6 }}>
        Inspect AWS resources, prepare only what is missing, then migrate a Docker/Podman image to ECR and ECS Fargate.
      </p>
    </header>

    <section style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 16, display: "grid", gap: 12 }}>
      <h3 style={{ margin: 0 }}>1. AWS account and infrastructure</h3>
      <label><span style={labelStyle}>AWS Region</span>
        <select value={region} onChange={e => setRegion(e.target.value)} style={fieldStyle}>
          <option value="ap-south-1">Asia Pacific (Mumbai) 鈥� ap-south-1</option>
          <option value="ap-south-2">Asia Pacific (Hyderabad) 鈥� ap-south-2</option>
          <option value="us-east-1">US East (N. Virginia) 鈥� us-east-1</option>
          <option value="us-west-2">US West (Oregon) 鈥� us-west-2</option>
          <option value="eu-west-1">Europe (Ireland) 鈥� eu-west-1</option>
        </select>
      </label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" disabled={!!busy} onClick={inspect}>{busy === "inspect" ? "Inspecting鈥�" : "Inspect AWS (read-only)"}</button>
        <button type="button" disabled={!!busy} onClick={prepare}>{busy === "prepare" ? "Preparing鈥�" : "Prepare missing infrastructure"}</button>
      </div>
      <p style={{ color: "#6b7280", fontSize: 12, margin: 0 }}>
        Preparation can create ECR, ECS, IAM, CloudWatch, VPC, subnet, route-table, internet-gateway, and security-group resources where permitted.
        It does not create NAT gateways or open application ports to the public internet.
      </p>
      <ErrorPanel error={error} />
      {report && <div style={{ display: "grid", gap: 10 }}>
        <div style={{ background: "#f9fafb", padding: 10, borderRadius: 8 }}>
          <strong>Account:</strong> {report.identity?.account || "Unknown"}{" "}
          <span style={{ color: "#6b7280" }}>({report.identity?.arn || "ARN unavailable"})</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))", gap: 8 }}>
          {[
            ["Networking", resources.network?.status || "unknown", resources.network?.message],
            ["ECS cluster", resources.ecsClusterStatus || "unknown", `${resources.ecsClusters?.length || 0} active cluster(s)`],
            ["Execution role", resources.executionRole?.status || "unknown", resources.executionRole?.arn || resources.executionRole?.name],
          ].map(([name, status, detail]) => <div key={name} style={{ border: "1px solid #e5e7eb", padding: 10, borderRadius: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}><strong>{name}</strong><StatusPill status={status} /></div>
            <div style={{ fontSize: 12, color: "#4b5563", marginTop: 6, overflowWrap: "anywhere" }}>{detail || "No detail returned"}</div>
          </div>)}
        </div>
        {report.networking?.selected && <div style={{ fontSize: 13 }}>
          <strong>Recommended VPC:</strong> {report.networking.selected.vpcId} 路 <strong>Subnets:</strong> {(report.networking.selected.subnetIds || []).join(", ") || "None"}
        </div>}
        <h4 style={{ margin: "4px 0" }}>Permission and API checks</h4>
        {actions.map((item, index) => <div key={index} style={{ padding: 10, borderRadius: 8, background: item.ok ? "#f0fdf4" : "#fef2f2" }}>
          <strong>{item.ok ? "Accessible" : "Blocked / failed"}</strong>
          {!item.ok && <ErrorPanel error={item.diagnostic} />}
        </div>)}
      </div>}
      {prepared && <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: 8, padding: 12 }}>
        <strong>Infrastructure prepared</strong>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 12 }}>{JSON.stringify(prepared, null, 2)}</pre>
      </div>}
    </section>

    <section style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 16, display: "grid", gap: 12 }}>
      <h3 style={{ margin: 0 }}>2. Source VM container</h3>
      <div style={{ color: "#4b5563", fontSize: 13 }}>Uses the existing ATM saved source connection. No source credentials are sent back to the browser.</div>
      <label><span style={labelStyle}>Runtime</span>
        <select value={runtime} onChange={e => setRuntime(e.target.value)} style={fieldStyle}>
          <option value="auto">Auto-detect Docker / Podman</option>
          <option value="docker">Docker</option><option value="podman">Podman</option>
        </select>
      </label>
      <button type="button" disabled={!!busy || !sourceConnectionId} onClick={discoverContainers}>
        {busy === "containers" ? "Discovering鈥�" : "Discover source containers"}
      </button>
      <ErrorPanel error={networkError} />
      {containers.length > 0 && <>
        <label><span style={labelStyle}>Container</span>
          <select value={containerId} onChange={e => setContainerId(e.target.value)} style={fieldStyle}>
            {containers.map(c => <option key={c.id} value={c.id}>{c.name || c.id} 鈥� {c.image} ({c.status})</option>)}
          </select>
        </label>
        <div style={{ overflowX: "auto" }}><table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
          <thead><tr>{["Name", "Image", "Status", "Ports", "Runtime"].map(x => <th key={x} style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb", padding: 8 }}>{x}</th>)}</tr></thead>
          <tbody>{containers.map(c => <tr key={c.id}>{[c.name || c.id, c.image, c.status, c.ports || "鈥�", c.runtime].map((v, i) => <td key={i} style={{ borderBottom: "1px solid #f3f4f6", padding: 8 }}>{v}</td>)}</tr>)}</tbody>
        </table></div>
      </>}
    </section>

    <section style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 16, display: "grid", gap: 12 }}>
      <h3 style={{ margin: 0 }}>3. ECR and ECS deployment settings</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12 }}>
        <label><span style={labelStyle}>ECR repository</span><input style={fieldStyle} value={repositoryName} onChange={e => setRepositoryName(e.target.value)} /></label>
        <label><span style={labelStyle}>ECS cluster</span><input style={fieldStyle} value={clusterName} onChange={e => setClusterName(e.target.value)} /></label>
        <label><span style={labelStyle}>ECS service</span><input style={fieldStyle} value={serviceName} onChange={e => setServiceName(e.target.value)} /></label>
        <label><span style={labelStyle}>Container port (optional)</span><input style={fieldStyle} type="number" min="1" max="65535" value={containerPort} onChange={e => setContainerPort(e.target.value)} placeholder="e.g. 8080" /></label>
        <label><span style={labelStyle}>Fargate CPU</span><select style={fieldStyle} value={cpu} onChange={e => { setCpu(e.target.value); const next = ({ "256":"512", "512":"1024", "1024":"2048", "2048":"4096", "4096":"8192", "8192":"16384", "16384":"32768" })[e.target.value]; setMemory(next); }}>
          {["256","512","1024","2048","4096","8192","16384"].map(v => <option key={v} value={v}>{v} CPU units</option>)}
        </select></label>
        <label><span style={labelStyle}>Memory (MiB)</span><select style={fieldStyle} value={memory} onChange={e => setMemory(e.target.value)}>{memoryOptions.map(v => <option key={v} value={v}>{v} MiB</option>)}</select></label>
        <label><span style={labelStyle}>Desired tasks</span><input style={fieldStyle} type="number" min="0" max="100" value={desiredCount} onChange={e => setDesiredCount(e.target.value)} /></label>
        <label><span style={labelStyle}>CloudWatch log group</span><input style={fieldStyle} value={logGroup} onChange={e => setLogGroup(e.target.value)} /></label>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input type="checkbox" checked={assignPublicIp} onChange={e => setAssignPublicIp(e.target.checked)} />
        Assign public IP to Fargate tasks (needed for direct internet access from public subnets without NAT)
      </label>
      <button type="button" onClick={() => setShowAdvanced(v => !v)}>{showAdvanced ? "Hide advanced options" : "Show advanced options"}</button>
      {showAdvanced && <div style={{ display: "grid", gap: 10 }}>
        <label><span style={labelStyle}>Execution role ARN (optional; otherwise prepared/discovered)</span><input style={fieldStyle} value={executionRoleArn} onChange={e => setExecutionRoleArn(e.target.value)} placeholder="arn:aws:iam::123456789012:role/ecsTaskExecutionRole" /></label>
        <label><span style={labelStyle}>Container health-check command (optional)</span><input style={fieldStyle} value={healthCheckCommand} onChange={e => setHealthCheckCommand(e.target.value)} placeholder="curl -f http://localhost:8080/health || exit 1" /></label>
      </div>}
      <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8, padding: 10, fontSize: 13 }}>
        <strong>Migration limitation:</strong> this workflow transfers the image. It does not automatically migrate environment variables, secrets, bind mounts, persistent volumes, host networking, or external dependencies. Review those before production cutover.
      </div>
      <button type="button" disabled={!!busy || !sourceConnectionId || !containerId} onClick={startMigration}>
        {busy === "migrate" ? "Starting鈥�" : "Migrate container image to ECR and ECS"}
      </button>
    </section>

    {job && <section style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 16, display: "grid", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>4. Migration progress</h3><StatusPill status={job.status} />
      </div>
      <div>{job.message}</div>
      <div style={{ height: 8, background: "#e5e7eb", borderRadius: 99, overflow: "hidden" }}><div style={{ height: "100%", width: `${job.progress || 0}%`, background: "#2563eb", transition: "width .2s" }} /></div>
      <div style={{ fontSize: 12, color: "#6b7280" }}>{job.phase} 路 {job.progress || 0}% 路 Job ID: {job.jobId}</div>
      {job.error && <ErrorPanel error={job.error} />}
      {job.result && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", background: "#f9fafb", borderRadius: 8, padding: 12, fontSize: 12 }}>{JSON.stringify(job.result, null, 2)}</pre>}
      {!["succeeded", "failed", "cancelled"].includes(job.status) && <button type="button" disabled={!!busy} onClick={cancel}>{busy === "cancel" ? "Requesting鈥�" : "Cancel migration"}</button>}
    </section>}
  </div>;
}