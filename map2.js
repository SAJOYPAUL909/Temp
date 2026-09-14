"use client";

import React, { useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  MarkerType,
} from "@xyflow/react";

import {
  Monitor,
  Server,
  Database,
  ShieldCheck,
  Zap,
  MessageSquare,
  HardDrive,
  Network,
  Container,
  Globe,
  Settings,
  Box,
  Cloud,
  Workflow,
  Cpu,
} from "lucide-react";

import "@xyflow/react/dist/style.css";

const DEFAULT_API_URL = "http://localhost:1201/api/mapping";

/* =========================================================
   Helpers
========================================================= */

function safeId(value) {
  return String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9_.:-]/g, "_");
}

function getIcon(group, tech, isContainer) {
  if (isContainer) return Container;

  const value = `${group || ""} ${tech || ""}`.toLowerCase();

  if (
    value.includes("database") ||
    value.includes("postgres") ||
    value.includes("mysql") ||
    value.includes("oracle") ||
    value.includes("mongo") ||
    value.includes("redis")
  ) {
    return Database;
  }

  if (value.includes("auth") || value.includes("keycloak")) {
    return ShieldCheck;
  }

  if (value.includes("queue") || value.includes("kafka") || value.includes("rabbit")) {
    return MessageSquare;
  }

  if (value.includes("cache")) {
    return Zap;
  }

  if (value.includes("storage") || value.includes("minio")) {
    return HardDrive;
  }

  if (value.includes("proxy") || value.includes("nginx") || value.includes("haproxy")) {
    return Network;
  }

  if (
    value.includes("frontend") ||
    value.includes("react") ||
    value.includes("next") ||
    value.includes("angular") ||
    value.includes("vue")
  ) {
    return Monitor;
  }

  if (
    value.includes("cloud") ||
    value.includes("aws") ||
    value.includes("gcp") ||
    value.includes("azure")
  ) {
    return Cloud;
  }

  if (value.includes("api") || value.includes("backend") || value.includes("fastapi")) {
    return Server;
  }

  if (value.includes("service")) {
    return Workflow;
  }

  if (value.includes("cpu") || value.includes("worker")) {
    return Cpu;
  }

  return Box;
}

/* =========================================================
   Application Node
========================================================= */

function ApplicationNode({ data }) {
  const Icon = getIcon(data.group, data.tech, data.container);

  return (
    <div
      style={{
        width: 285,
        background: "#ffffff",
        border: `1px solid ${data.container ? "#6366f1" : "#cbd5e1"}`,
        borderRadius: 12,
        boxShadow: "0 4px 14px rgba(0,0,0,0.08)",
        overflow: "hidden",
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 8,
          height: 8,
          background: "#64748b",
        }}
      />

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "11px 13px",
          borderBottom: "1px solid #e2e8f0",
          background: data.container ? "#f5f3ff" : "#f8fafc",
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 9,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            flexShrink: 0,
          }}
        >
          <Icon size={21} strokeWidth={1.8} />
        </div>

        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: "#0f172a",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {data.label}
          </div>

          <div
            style={{
              marginTop: 2,
              fontSize: 11,
              color: "#64748b",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {data.tech || "Unknown technology"}
          </div>
        </div>
      </div>

      <div style={{ padding: 12 }}>
        <InfoRow label="VM" value={data.vm || "Unknown"} />
        <InfoRow label="IP" value={data.host || "Unknown"} />
        <InfoRow
          label="Port"
          value={
            data.port !== null &&
            data.port !== undefined &&
            data.port !== ""
              ? String(data.port)
              : "Unknown"
          }
        />

        {data.group && <InfoRow label="Type" value={data.group} />}

        {data.container && (
          <InfoRow
            label="Container"
            value={data.container_name || "Container"}
          />
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 8,
          height: 8,
          background: "#64748b",
        }}
      />
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        marginBottom: 6,
        fontSize: 11,
      }}
    >
      <span style={{ color: "#64748b" }}>{label}</span>

      <span
        style={{
          color: "#334155",
          fontWeight: 600,
          textAlign: "right",
          maxWidth: 185,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

/* =========================================================
   Connection Edge
========================================================= */

function ApplicationEdge({
  id,
  source,
  target,
  data,
  markerEnd,
}) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: data?.sourceX,
    sourceY: data?.sourceY,
    sourcePosition: Position.Right,
    targetX: data?.targetX,
    targetY: data?.targetY,
    targetPosition: Position.Left,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          strokeWidth: 2,
          stroke: "#64748b",
        }}
      />

      {(data?.protocol || data?.target) && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              background: "#ffffff",
              border: "1px solid #cbd5e1",
              borderRadius: 5,
              padding: "3px 7px",
              fontSize: 10,
              fontWeight: 600,
              color: "#475569",
              pointerEvents: "all",
              boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
            }}
          >
            {data?.protocol || data?.target}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

/* =========================================================
   Normalization
========================================================= */

function normalizeNode(nodeId, node, vmInfo = {}) {
  const value =
    typeof node === "string"
      ? {
          label: node,
        }
      : node || {};

  const container =
    Boolean(
      value.container ??
        value.is_container ??
        value.containerized ??
        value.isContainer
    );

  return {
    id: nodeId,
    label:
      value.label ||
      value.name ||
      value.application ||
      value.service ||
      nodeId,

    tech:
      value.tech ||
      value.technology ||
      value.framework ||
      "Unknown",

    port:
      value.port ??
      value.Port ??
      value.container_port ??
      value.containerPort ??
      null,

    host:
      value.host ||
      value.Host ||
      value.ip ||
      value.ip_address ||
      value.container_ip ||
      vmInfo.host ||
      "127.0.0.1",

    vm:
      value.vm ||
      value.vm_name ||
      value.virtual_machine ||
      value.hostname ||
      vmInfo.hostname ||
      vmInfo.name ||
      vmInfo.id ||
      "Unknown VM",

    vmId:
      value.vm_id ||
      value.vmId ||
      vmInfo.id ||
      vmInfo.vm_id ||
      value.vm ||
      "unknown-vm",

    group:
      value.group ||
      value.Group ||
      "OTHER",

    container,

    container_name:
      value.container_name ||
      value.containerName ||
      value.container_id ||
      value.containerId ||
      (container ? value.name : null),

    container_ip:
      value.container_ip ||
      value.containerIp ||
      null,
  };
}

/* =========================================================
   Response Parsing
========================================================= */

function parseMappingResponse(input) {
  if (!input) {
    return {
      about: "",
      nodes: [],
      connections: [],
    };
  }

  const records = Array.isArray(input) ? input : [input];

  const globalNodes = new Map();
  const localToGlobal = new Map();
  const connections = [];
  const connectionKeys = new Set();

  let about = "";

  records.forEach((record, recordIndex) => {
    const mapping = record?.mapping || record;

    if (!about && mapping?.About_Application) {
      about = mapping.About_Application;
    }

    const vmInfo =
      mapping?.VM ||
      mapping?.vm ||
      mapping?.VM_Info ||
      mapping?.vm_info ||
      {};

    const vmId =
      vmInfo?.id ||
      vmInfo?.vm_id ||
      mapping?.vm_id ||
      record?.vm_id ||
      mapping?.vm ||
      record?.vm ||
      `vm_${recordIndex + 1}`;

    const vmName =
      vmInfo?.hostname ||
      vmInfo?.name ||
      mapping?.vm_name ||
      record?.vm_name ||
      String(vmId);

    const vmHost =
      vmInfo?.host ||
      vmInfo?.ip ||
      mapping?.host ||
      record?.host ||
      record?.ip ||
      null;

    const vm = {
      id: vmId,
      hostname: vmName,
      host: vmHost,
    };

    const rawNodes = mapping?.Nodes || {};

    Object.entries(rawNodes).forEach(([localId, rawNode]) => {
      const normalized = normalizeNode(localId, rawNode, vm);

      const stableId = safeId(
        `${vmId}::${localId}`
      );

      normalized.id = stableId;
      normalized.vm = normalized.vm || vmName;
      normalized.vmId = vmId;

      globalNodes.set(stableId, normalized);

      localToGlobal.set(
        `${recordIndex}::${localId}`,
        stableId
      );

      /*
       * Also allow resolving the local node ID when it is unique.
       */
      if (!localToGlobal.has(`local::${localId}`)) {
        localToGlobal.set(`local::${localId}`, stableId);
      } else {
        localToGlobal.set(`local::${localId}`, null);
      }
    });

    const rawConnections = Array.isArray(mapping?.Connections)
      ? mapping.Connections
      : [];

    rawConnections.forEach((connection) => {
      if (!connection) return;

      const fromLocal =
        connection.from ||
        connection.source ||
        connection.From;

      const toLocal =
        connection.to ||
        connection.target ||
        connection.To;

      if (!fromLocal || !toLocal) return;

      let fromId =
        localToGlobal.get(`${recordIndex}::${fromLocal}`) ||
        localToGlobal.get(`local::${fromLocal}`);

      let toId =
        localToGlobal.get(`${recordIndex}::${toLocal}`) ||
        localToGlobal.get(`local::${toLocal}`);

      /*
       * Connection may already contain globally scoped IDs.
       */
      if (!fromId && globalNodes.has(fromLocal)) {
        fromId = fromLocal;
      }

      if (!toId && globalNodes.has(toLocal)) {
        toId = toLocal;
      }

      /*
       * Never create edges to nodes that do not exist.
       */
      if (!fromId || !toId) return;

      /*
       * Never allow self connections.
       */
      if (fromId === toId) return;

      const protocol =
        connection.protocol ||
        connection.Protocol ||
        "";

      const source =
        connection.source_address ||
        connection.source ||
        "";

      const target =
        connection.target_address ||
        connection.target ||
        "";

      const key = `${fromId}|${toId}|${protocol}|${source}|${target}`;

      if (connectionKeys.has(key)) return;

      connectionKeys.add(key);

      connections.push({
        id: `edge_${connections.length + 1}`,
        source: fromId,
        target: toId,
        type: "applicationEdge",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 18,
          height: 18,
        },
        data: {
          protocol,
          source,
          target,
        },
      });
    });
  });

  return {
    about,
    nodes: Array.from(globalNodes.values()),
    connections,
  };
}

/* =========================================================
   Dynamic Layout
========================================================= */

function layoutNodes(nodes, connections) {
  if (!nodes.length) return [];

  const incoming = new Map();
  const outgoing = new Map();

  nodes.forEach((node) => {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
  });

  connections.forEach((edge) => {
    if (
      incoming.has(edge.target) &&
      outgoing.has(edge.source)
    ) {
      incoming.get(edge.target).push(edge.source);
      outgoing.get(edge.source).push(edge.target);
    }
  });

  const levels = new Map();
  const queue = [];

  nodes.forEach((node) => {
    if (incoming.get(node.id).length === 0) {
      levels.set(node.id, 0);
      queue.push(node.id);
    }
  });

  /*
   * If the graph is cyclic or completely disconnected,
   * initialize remaining nodes at level 0.
   */
  nodes.forEach((node) => {
    if (!levels.has(node.id)) {
      levels.set(node.id, 0);
      queue.push(node.id);
    }
  });

  while (queue.length) {
    const current = queue.shift();
    const currentLevel = levels.get(current);

    outgoing.get(current).forEach((next) => {
      const nextLevel = currentLevel + 1;

      if (
        !levels.has(next) ||
        nextLevel > levels.get(next)
      ) {
        levels.set(next, nextLevel);
      }

      if (!queue.includes(next)) {
        queue.push(next);
      }
    });
  }

  const columns = new Map();

  nodes.forEach((node) => {
    const level = levels.get(node.id) || 0;

    if (!columns.has(level)) {
      columns.set(level, []);
    }

    columns.get(level).push(node);
  });

  const positioned = [];

  Array.from(columns.keys())
    .sort((a, b) => a - b)
    .forEach((level) => {
      const column = columns.get(level);

      /*
       * Keep applications from the same VM close together.
       */
      column.sort((a, b) => {
        if (a.vmId !== b.vmId) {
          return String(a.vmId).localeCompare(String(b.vmId));
        }

        return String(a.label).localeCompare(String(b.label));
      });

      column.forEach((node, index) => {
        positioned.push({
          id: node.id,
          type: "applicationNode",
          position: {
            x: level * 390,
            y: index * 190,
          },
          data: node,
        });
      });
    });

  return positioned;
}

/* =========================================================
   React Flow Diagram
========================================================= */

function Diagram({ data }) {
  const parsed = useMemo(
    () => parseMappingResponse(data),
    [data]
  );

  const flowNodes = useMemo(
    () =>
      layoutNodes(
        parsed.nodes,
        parsed.connections
      ),
    [parsed.nodes, parsed.connections]
  );

  const [selectedNode, setSelectedNode] = useState(null);

  const nodeTypes = useMemo(
    () => ({
      applicationNode: ApplicationNode,
    }),
    []
  );

  const edgeTypes = useMemo(
    () => ({
      applicationEdge: ApplicationEdge,
    }),
    []
  );

  return (
    <div
      style={{
        width: "100%",
        height: "calc(100vh - 80px)",
        minHeight: 650,
        position: "relative",
        background: "#f8fafc",
      }}
    >
      <ReactFlow
        nodes={flowNodes}
        edges={parsed.connections}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{
          padding: 0.2,
        }}
        onNodeClick={(_, node) => {
          setSelectedNode(node.data);
        }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
      >
        <Background gap={20} size={1} />
        <Controls />
        <MiniMap
          nodeStrokeWidth={2}
          zoomable
          pannable
        />
      </ReactFlow>

      {parsed.about && (
        <div
          style={{
            position: "absolute",
            top: 15,
            left: 15,
            zIndex: 10,
            maxWidth: 420,
            padding: 14,
            borderRadius: 10,
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            boxShadow: "0 4px 14px rgba(0,0,0,0.08)",
          }}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: "#334155",
              marginBottom: 5,
            }}
          >
            Application
          </div>

          <div
            style={{
              fontSize: 12,
              lineHeight: 1.5,
              color: "#64748b",
            }}
          >
            {parsed.about}
          </div>
        </div>
      )}

      {selectedNode && (
        <div
          style={{
            position: "absolute",
            right: 15,
            top: 15,
            zIndex: 20,
            width: 310,
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 12,
            boxShadow: "0 8px 25px rgba(0,0,0,0.12)",
            padding: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 14,
            }}
          >
            <div
              style={{
                fontSize: 15,
                fontWeight: 700,
                color: "#0f172a",
              }}
            >
              {selectedNode.label}
            </div>

            <button
              onClick={() => setSelectedNode(null)}
              style={{
                border: "none",
                background: "transparent",
                cursor: "pointer",
                fontSize: 18,
                color: "#64748b",
              }}
            >
              ×
            </button>
          </div>

          <DetailRow
            label="Technology"
            value={selectedNode.tech}
          />

          <DetailRow
            label="VM"
            value={selectedNode.vm}
          />

          <DetailRow
            label="VM ID"
            value={selectedNode.vmId}
          />

          <DetailRow
            label="Host / IP"
            value={selectedNode.host}
          />

          <DetailRow
            label="Port"
            value={
              selectedNode.port ??
              "Unknown"
            }
          />

          <DetailRow
            label="Group"
            value={selectedNode.group}
          />

          <DetailRow
            label="Container"
            value={
              selectedNode.container
                ? selectedNode.container_name || "Yes"
                : "No"
            }
          />

          {selectedNode.container_ip && (
            <DetailRow
              label="Container IP"
              value={selectedNode.container_ip}
            />
          )}
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div
      style={{
        padding: "8px 0",
        borderBottom: "1px solid #f1f5f9",
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "#94a3b8",
          marginBottom: 2,
        }}
      >
        {label}
      </div>

      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: "#334155",
          wordBreak: "break-word",
        }}
      >
        {value === null ||
        value === undefined ||
        value === ""
          ? "Unknown"
          : String(value)}
      </div>
    </div>
  );
}

/* =========================================================
   Main Component
========================================================= */

export default function ApplicationArchitectureDiagram({
  data,
  apiUrl = DEFAULT_API_URL,
}) {
  const [mappingData, setMappingData] = useState(data || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMapping(source) {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          source,
        }),
      });

      if (!response.ok) {
        throw new Error(
          `API failed with status ${response.status}`
        );
      }

      const result = await response.json();

      setMappingData(result);
    } catch (err) {
      setError(
        err?.message ||
          "Failed to load application mapping"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <ReactFlowProvider>
      <div
        style={{
          width: "100%",
          height: "100%",
          minHeight: 700,
          position: "relative",
        }}
      >
        {loading && (
          <div
            style={{
              position: "absolute",
              top: 15,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 50,
              background: "#ffffff",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              padding: "8px 14px",
              fontSize: 12,
              color: "#475569",
              boxShadow:
                "0 4px 12px rgba(0,0,0,0.08)",
            }}
          >
            Loading application mapping...
          </div>
        )}

        {error && (
          <div
            style={{
              position: "absolute",
              top: 15,
              left: 15,
              zIndex: 50,
              background: "#ffffff",
              border: "1px solid #fecaca",
              borderRadius: 8,
              padding: "10px 14px",
              fontSize: 12,
              color: "#b91c1c",
              boxShadow:
                "0 4px 12px rgba(0,0,0,0.08)",
            }}
          >
            {error}
          </div>
        )}

        {mappingData ? (
          <Diagram data={mappingData} />
        ) : (
          <div
            style={{
              height: "100%",
              minHeight: 650,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#64748b",
              fontSize: 14,
            }}
          >
            No application mapping data available.
          </div>
        )}
      </div>
    </ReactFlowProvider>
  );
}