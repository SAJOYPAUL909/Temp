"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  addEdge,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

/* ============================================================
   CONFIGURATION
   ============================================================ */

const DEFAULT_API_URL =
  "http://localhost:1201/api/mapping";


/* ============================================================
   HELPERS
   ============================================================ */

function safeId(value) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_-]/g, "_");
}


function getIcon(group, tech) {
  const value = `${group || ""} ${tech || ""}`.toLowerCase();

  if (
    value.includes("frontend") ||
    value.includes("ui") ||
    value.includes("react") ||
    value.includes("angular") ||
    value.includes("vue")
  ) {
    return "🖥️";
  }

  if (
    value.includes("database") ||
    value.includes("db") ||
    value.includes("postgres") ||
    value.includes("mysql") ||
    value.includes("oracle") ||
    value.includes("mongodb") ||
    value.includes("mongo")
  ) {
    return "🗄️";
  }

  if (
    value.includes("cache") ||
    value.includes("redis")
  ) {
    return "⚡";
  }

  if (
    value.includes("queue") ||
    value.includes("kafka") ||
    value.includes("rabbit")
  ) {
    return "📨";
  }

  if (
    value.includes("storage") ||
    value.includes("minio") ||
    value.includes("s3")
  ) {
    return "📦";
  }

  if (
    value.includes("service") ||
    value.includes("microservice")
  ) {
    return "🔧";
  }

  if (
    value.includes("backend") ||
    value.includes("api") ||
    value.includes("fastapi") ||
    value.includes("flask") ||
    value.includes("java") ||
    value.includes("node")
  ) {
    return "⚙️";
  }

  return "●";
}


/* ============================================================
   CUSTOM NODE
   ============================================================ */

function ApplicationNode({ data }) {
  const {
    label,
    tech,
    port,
    host,
    group,
    description,
  } = data;

  return (
    <div className="app-map-node">

      <Handle
        type="target"
        position={Position.Left}
        className="app-map-handle"
      />

      <div className="app-map-node-header">

        <div className="app-map-node-icon">
          {getIcon(group, tech)}
        </div>

        <div className="app-map-node-title">
          {label || data.id}
        </div>

      </div>

      <div className="app-map-node-body">

        {tech && (
          <div className="app-map-row">
            <span className="app-map-key">
              Tech
            </span>

            <span className="app-map-value">
              {tech}
            </span>
          </div>
        )}

        {port !== undefined &&
          port !== null &&
          port !== "" && (
            <div className="app-map-row">
              <span className="app-map-key">
                Port
              </span>

              <span className="app-map-value">
                {port}
              </span>
            </div>
          )}

        {host && (
          <div className="app-map-row">
            <span className="app-map-key">
              Host
            </span>

            <span className="app-map-value">
              {host}
            </span>
          </div>
        )}

        {description && (
          <div className="app-map-description">
            {description}
          </div>
        )}

        <div className="app-map-group">
          {group || "Application"}
        </div>

      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="app-map-handle"
      />

    </div>
  );
}


/* ============================================================
   NORMALIZE NODE DATA
   ============================================================ */

function normalizeNode(nodeId, nodeData) {
  const data =
    nodeData &&
    typeof nodeData === "object"
      ? nodeData
      : {};

  return {
    id: safeId(nodeId),

    type: "applicationNode",

    position: {
      x: 0,
      y: 0,
    },

    data: {
      id: safeId(nodeId),

      originalId: nodeId,

      label:
        data.label ||
        data.name ||
        nodeId,

      tech:
        data.tech ||
        data.technology ||
        "",

      port:
        data.port ??
        data.Port ??
        "",

      host:
        data.host ||
        data.Host ||
        "",

      group:
        data.group ||
        data.Group ||
        "Application",

      description:
        data.description ||
        data.About_Application ||
        "",

      ...data,
    },
  };
}


/* ============================================================
   EXTRACT NODES + CONNECTIONS FROM API RESPONSE
   ============================================================ */

function parseApiResponse(response) {
  const nodesMap = new Map();
  const connections = [];

  if (!Array.isArray(response)) {
    return {
      nodes: [],
      edges: [],
    };
  }

  response.forEach((record) => {
    if (!record || typeof record !== "object") {
      return;
    }

    const recommendation =
      record.recommendation || {};

    /*
     * --------------------------------------------------------
     * Nodes
     * --------------------------------------------------------
     */

    const nodes =
      recommendation.Nodes ||
      recommendation.nodes ||
      {};

    if (
      nodes &&
      typeof nodes === "object" &&
      !Array.isArray(nodes)
    ) {
      Object.entries(nodes).forEach(
        ([nodeId, nodeData]) => {

          const id = safeId(nodeId);

          if (!id) {
            return;
          }

          /*
           * If the same node occurs in multiple
           * records, merge its information.
           */

          if (nodesMap.has(id)) {
            const existing =
              nodesMap.get(id);

            nodesMap.set(id, {
              ...existing,
              ...(nodeData || {}),
            });
          } else {
            nodesMap.set(
              id,
              normalizeNode(
                nodeId,
                nodeData
              )
            );
          }
        }
      );
    }

    /*
     * --------------------------------------------------------
     * Connections
     * --------------------------------------------------------
     */

    const recordConnections =
      recommendation.Connections ||
      recommendation.connections ||
      [];

    if (Array.isArray(recordConnections)) {
      recordConnections.forEach(
        (connection) => {
          if (!connection) {
            return;
          }

          const from =
            connection.from ||
            connection.source;

          const to =
            connection.to ||
            connection.target;

          if (!from || !to) {
            return;
          }

          connections.push({
            from,
            to,

            label:
              connection.label ||
              connection.protocol ||
              connection.type ||
              "",

            ...connection,
          });
        }
      );
    }
  });


  /* ==========================================================
     Create missing nodes referenced by Connections
     ========================================================== */

  connections.forEach((connection) => {

    const sourceId =
      safeId(connection.from);

    const targetId =
      safeId(connection.to);

    if (
      sourceId &&
      !nodesMap.has(sourceId)
    ) {
      nodesMap.set(
        sourceId,
        normalizeNode(
          connection.from,
          {
            label: connection.from,
            tech: "Unknown",
            group: "Unknown",
          }
        )
      );
    }

    if (
      targetId &&
      !nodesMap.has(targetId)
    ) {
      nodesMap.set(
        targetId,
        normalizeNode(
          connection.to,
          {
            label: connection.to,
            tech: "Unknown",
            group: "Unknown",
          }
        )
      );
    }
  });


  const nodes = Array.from(
    nodesMap.values()
  );


  /* ==========================================================
     Create React Flow edges
     ========================================================== */

  const edges = [];

  const edgeSet = new Set();

  connections.forEach(
    (connection, index) => {

      const source =
        safeId(connection.from);

      const target =
        safeId(connection.to);

      if (!source || !target) {
        return;
      }

      const edgeKey =
        `${source}->${target}`;

      /*
       * Prevent duplicate connections.
       */

      if (edgeSet.has(edgeKey)) {
        return;
      }

      edgeSet.add(edgeKey);

      edges.push({
        id:
          `connection-${source}-${target}-${index}`,

        source,

        target,

        type: "smoothstep",

        animated: true,

        markerEnd: {
          type: MarkerType.ArrowClosed,
        },

        label:
          connection.label || "",

        style: {
          strokeWidth: 2,
        },

        labelStyle: {
          fontSize: 10,
        },
      });
    }
  );


  return {
    nodes,
    edges,
  };
}


/* ============================================================
   AUTOMATIC ARCHITECTURE LAYOUT
   ============================================================ */

function layoutNodes(nodes, edges) {

  if (!nodes.length) {
    return [];
  }

  /*
   * Determine hierarchy using graph relationships.
   *
   * Sources with no incoming edge are considered
   * starting points.
   *
   * This makes:
   *
   * Frontend -> Backend -> Database
   *
   * appear naturally from left to right.
   */

  const incoming = new Map();
  const outgoing = new Map();

  nodes.forEach((node) => {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
  });

  edges.forEach((edge) => {

    if (!outgoing.has(edge.source)) {
      outgoing.set(edge.source, []);
    }

    if (!incoming.has(edge.target)) {
      incoming.set(edge.target, []);
    }

    outgoing
      .get(edge.source)
      .push(edge.target);

    incoming
      .get(edge.target)
      .push(edge.source);
  });


  /*
   * Calculate levels.
   */

  const levels = new Map();

  const roots = nodes.filter(
    (node) =>
      (incoming.get(node.id) || [])
        .length === 0
  );


  /*
   * Completely independent nodes
   * are handled separately.
   */

  const connectedNodeIds =
    new Set();

  edges.forEach((edge) => {
    connectedNodeIds.add(
      edge.source
    );

    connectedNodeIds.add(
      edge.target
    );
  });


  const queue = [];

  roots.forEach((root) => {

    levels.set(root.id, 0);

    queue.push(root.id);

  });


  /*
   * If there are cycles and therefore
   * no roots, start from first node.
   */

  if (!queue.length && nodes.length) {

    levels.set(
      nodes[0].id,
      0
    );

    queue.push(
      nodes[0].id
    );
  }


  while (queue.length) {

    const current =
      queue.shift();

    const currentLevel =
      levels.get(current) || 0;

    const children =
      outgoing.get(current) || [];

    children.forEach((child) => {

      const nextLevel =
        currentLevel + 1;

      const existingLevel =
        levels.get(child);

      if (
        existingLevel === undefined ||
        nextLevel > existingLevel
      ) {

        /*
         * Limit maximum level so a
         * circular graph doesn't keep
         * increasing forever.
         */

        if (nextLevel <= nodes.length) {

          levels.set(
            child,
            nextLevel
          );

          queue.push(child);
        }
      }
    });
  }


  /*
   * Put unvisited connected nodes at
   * the end.
   */

  let maxLevel = 0;

  levels.forEach((level) => {
    maxLevel =
      Math.max(
        maxLevel,
        level
      );
  });


  nodes.forEach((node) => {

    if (!levels.has(node.id)) {

      if (
        connectedNodeIds.has(node.id)
      ) {
        levels.set(
          node.id,
          maxLevel + 1
        );
      }
    }
  });


  /*
   * Group nodes by level.
   */

  const columns = {};

  nodes.forEach((node) => {

    let level =
      levels.get(node.id);

    /*
     * Independent nodes get their
     * own area.
     */

    if (level === undefined) {
      level = maxLevel + 2;
    }

    if (!columns[level]) {
      columns[level] = [];
    }

    columns[level].push(node);
  });


  /*
   * Sort nodes inside each level by
   * group.
   */

  Object.values(columns).forEach(
    (column) => {

      column.sort((a, b) => {

        const groupA =
          String(
            a.data?.group || ""
          );

        const groupB =
          String(
            b.data?.group || ""
          );

        return groupA.localeCompare(
          groupB
        );
      });

    }
  );


  /*
   * Generate positions.
   */

  const horizontalGap = 330;
  const verticalGap = 190;

  const result = [];

  Object.entries(columns).forEach(
    ([level, column]) => {

      const levelNumber =
        Number(level);

      column.forEach(
        (node, index) => {

          result.push({
            ...node,

            position: {
              x:
                levelNumber *
                horizontalGap,

              y:
                index *
                verticalGap,
            },
          });

        }
      );
    }
  );


  /*
   * Handle disconnected nodes better.
   *
   * Put them below the main architecture.
   */

  const independent =
    nodes.filter(
      (node) =>
        !connectedNodeIds.has(
          node.id
        )
    );

  independent.forEach(
    (node, index) => {

      const resultNode =
        result.find(
          (item) =>
            item.id === node.id
        );

      if (resultNode) {

        resultNode.position = {
          x:
            index *
            horizontalGap,

          y:
            600,
        };

      }

    }
  );


  return result;
}


/* ============================================================
   MAIN COMPONENT
   ============================================================ */

function ApplicationMappingInner({
  requestBody = {},
  apiUrl = DEFAULT_API_URL,
  height = "750px",
}) {

  const [
    nodes,
    setNodes,
    onNodesChange,
  ] = useNodesState([]);

  const [
    edges,
    setEdges,
    onEdgesChange,
  ] = useEdgesState([]);

  const [loading, setLoading] =
    useState(false);

  const [error, setError] =
    useState("");

  const [
    selectedNode,
    setSelectedNode,
  ] = useState(null);


  /* ==========================================================
     NODE TYPES
     ========================================================== */

  const nodeTypes = useMemo(
    () => ({
      applicationNode:
        ApplicationNode,
    }),
    []
  );


  /* ==========================================================
     FETCH API
     ========================================================== */

  const loadMapping =
    useCallback(async () => {

      setLoading(true);
      setError("");

      try {

        const response =
          await fetch(
            apiUrl,
            {
              method: "POST",

              headers: {
                "Content-Type":
                  "application/json",
              },

              body:
                JSON.stringify(
                  requestBody
                ),
            }
          );


        if (!response.ok) {

          throw new Error(
            `API request failed with status ${response.status}`
          );

        }


        const data =
          await response.json();


        const architecture =
          parseApiResponse(data);


        const positionedNodes =
          layoutNodes(
            architecture.nodes,
            architecture.edges
          );


        setNodes(
          positionedNodes
        );

        setEdges(
          architecture.edges
        );


      } catch (err) {

        console.error(
          "Application mapping error:",
          err
        );

        setError(
          err?.message ||
            "Unable to load application mapping."
        );

        setNodes([]);
        setEdges([]);

      } finally {

        setLoading(false);

      }

    }, [
      apiUrl,
      requestBody,
      setNodes,
      setEdges,
    ]);


  /* ==========================================================
     INITIAL LOAD
     ========================================================== */

  useEffect(() => {

    loadMapping();

  }, [loadMapping]);


  /* ==========================================================
     MANUAL CONNECTION
     ========================================================== */

  const onConnect =
    useCallback(
      (connection) => {

        setEdges(
          (currentEdges) =>
            addEdge(
              {
                ...connection,

                type: "smoothstep",

                animated: true,

                markerEnd: {
                  type:
                    MarkerType.ArrowClosed,
                },
              },

              currentEdges
            )
        );

      },
      [setEdges]
    );


  /* ==========================================================
     NODE CLICK
     ========================================================== */

  const onNodeClick =
    useCallback(
      (_, node) => {

        setSelectedNode(node);

      },
      []
    );


  return (
    <div
      style={{
        width: "100%",
        height,
        position: "relative",
        border:
          "1px solid #e2e8f0",
        borderRadius: "10px",
        overflow: "hidden",
        background: "#f8fafc",
      }}
    >

      {/* ======================================================
          HEADER
         ====================================================== */}

      <div
        style={{
          height: "58px",
          display: "flex",
          alignItems: "center",
          justifyContent:
            "space-between",
          padding: "0 16px",
          background: "#ffffff",
          borderBottom:
            "1px solid #e2e8f0",
          position: "relative",
          zIndex: 10,
        }}
      >

        <div>

          <span
            style={{
              fontSize: "15px",
              fontWeight: 600,
              color: "#0f172a",
            }}
          >
            Application Mapping
          </span>

          <span
            style={{
              marginLeft: "12px",
              fontSize: "12px",
              color: "#64748b",
            }}
          >
            {nodes.length} components
            {" · "}
            {edges.length} connections
          </span>

        </div>


        <button
          type="button"
          onClick={loadMapping}
          disabled={loading}
          style={{
            border:
              "1px solid #cbd5e1",
            background: "#ffffff",
            borderRadius: "6px",
            padding:
              "7px 12px",
            cursor:
              loading
                ? "not-allowed"
                : "pointer",
            fontSize: "12px",
            color: "#334155",
          }}
        >
          {loading
            ? "Loading..."
            : "Refresh"}
        </button>

      </div>


      {/* ======================================================
          ERROR
         ====================================================== */}

      {error && (
        <div
          style={{
            position:
              "absolute",
            zIndex: 20,
            top: "70px",
            left: "15px",
            right: "15px",
            padding: "12px",
            border:
              "1px solid #fecaca",
            borderRadius: "7px",
            background:
              "#fef2f2",
            color: "#991b1b",
            fontSize: "12px",
          }}
        >
          <strong>
            Mapping API Error
          </strong>

          <div
            style={{
              marginTop: "4px",
            }}
          >
            {error}
          </div>
        </div>
      )}


      {/* ======================================================
          LOADING
         ====================================================== */}

      {loading &&
        nodes.length === 0 && (
          <div
            style={{
              position:
                "absolute",
              zIndex: 15,
              top: "58px",
              bottom: 0,
              left: 0,
              right: 0,
              display: "flex",
              alignItems:
                "center",
              justifyContent:
                "center",
              background:
                "rgba(248,250,252,0.85)",
              color: "#475569",
              fontSize: "13px",
            }}
          >
            Loading application mapping...
          </div>
        )}


      {/* ======================================================
          REACT FLOW
         ====================================================== */}

      <div
        style={{
          width: "100%",
          height:
            "calc(100% - 58px)",
        }}
      >

        <ReactFlow
          nodes={nodes}
          edges={edges}

          nodeTypes={nodeTypes}

          onNodesChange={
            onNodesChange
          }

          onEdgesChange={
            onEdgesChange
          }

          onConnect={onConnect}

          onNodeClick={onNodeClick}

          fitView

          fitViewOptions={{
            padding: 0.25,
            maxZoom: 1.2,
          }}

          minZoom={0.15}

          maxZoom={2}

          nodesConnectable={false}

          deleteKeyCode={null}
        >

          <Background
            gap={20}
            size={1}
          />

          <Controls />

          <MiniMap
            pannable
            zoomable
          />

        </ReactFlow>

      </div>


      {/* ======================================================
          NODE INFORMATION PANEL
         ====================================================== */}

      {selectedNode && (

        <div
          style={{
            position:
              "absolute",

            zIndex: 30,

            top: "70px",

            right: "15px",

            width: "270px",

            background:
              "#ffffff",

            border:
              "1px solid #cbd5e1",

            borderRadius:
              "8px",

            boxShadow:
              "0 8px 25px rgba(15,23,42,0.15)",
          }}
        >

          <div
            style={{
              display:
                "flex",

              alignItems:
                "center",

              justifyContent:
                "space-between",

              padding:
                "11px 13px",

              borderBottom:
                "1px solid #e2e8f0",

              fontSize:
                "13px",

              fontWeight:
                600,

              color:
                "#0f172a",
            }}
          >

            <span>
              {selectedNode.data?.label ||
                selectedNode.id}
            </span>

            <button
              type="button"
              onClick={() =>
                setSelectedNode(null)
              }
              style={{
                border: "none",
                background:
                  "transparent",
                cursor: "pointer",
                fontSize: "18px",
                color:
                  "#64748b",
              }}
            >
              ×
            </button>

          </div>


          <div
            style={{
              padding:
                "11px 13px",
            }}
          >

            <InfoRow
              label="Node"
              value={
                selectedNode.data
                  ?.originalId ||
                selectedNode.id
              }
            />

            <InfoRow
              label="Technology"
              value={
                selectedNode.data
                  ?.tech ||
                "Unknown"
              }
            />

            <InfoRow
              label="Group"
              value={
                selectedNode.data
                  ?.group ||
                "Unknown"
              }
            />

            <InfoRow
              label="Host"
              value={
                selectedNode.data
                  ?.host ||
                "Unknown"
              }
            />

            <InfoRow
              label="Port"
              value={
                selectedNode.data
                  ?.port ||
                "Unknown"
              }
            />

          </div>

        </div>

      )}

    </div>
  );
}


/* ============================================================
   INFORMATION ROW
   ============================================================ */

function InfoRow({
  label,
  value,
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent:
          "space-between",
        gap: "10px",
        padding: "7px 0",
        borderBottom:
          "1px solid #f1f5f9",
        fontSize: "11px",
      }}
    >

      <span
        style={{
          color: "#64748b",
        }}
      >
        {label}
      </span>

      <strong
        style={{
          color: "#334155",
          textAlign: "right",
          wordBreak:
            "break-word",
          maxWidth: "160px",
        }}
      >
        {String(
          value ?? "Unknown"
        )}
      </strong>

    </div>
  );
}


/* ============================================================
   EXPORTED COMPONENT
   ============================================================ */

export default function AppArchitectureDiagram(
  props
) {
  return (
    <ReactFlowProvider>
      <ApplicationMappingInner
        {...props}
      />
    </ReactFlowProvider>
  );
}
