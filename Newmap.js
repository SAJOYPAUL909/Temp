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
  useNodesState,
  useEdgesState,
} from "@xyflow/react";

import {
  Monitor,
  Database,
  Server,
  Cpu,
  Zap,
  MessageSquare,
  HardDrive,
  Globe,
  Box,
  Network,
  ShieldCheck,
  AppWindow,
  RefreshCw,
  X,
} from "lucide-react";

import "@xyflow/react/dist/style.css";


/* ============================================================
   CONFIGURATION
   ============================================================ */

const API_URL =
  "http://localhost:1201/api/mapping";


/* ============================================================
   HELPERS
   ============================================================ */

function normalizeId(value) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_-]/g, "_");
}


function cleanText(value) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}


function escapeRegex(value) {
  return String(value).replace(
    /[.*+?^${}()|[\]\\]/g,
    "\\$&"
  );
}


/* ============================================================
   LUCIDE ICON SELECTION
   ============================================================ */

function getIcon(group, tech, label) {
  const value =
    `${group || ""} ${tech || ""} ${label || ""}`.toLowerCase();


  if (
    value.includes("frontend") ||
    value.includes("ui") ||
    value.includes("react") ||
    value.includes("next.js") ||
    value.includes("nextjs") ||
    value.includes("angular") ||
    value.includes("vue")
  ) {
    return Monitor;
  }


  if (
    value.includes("database") ||
    value.includes("db") ||
    value.includes("postgres") ||
    value.includes("mysql") ||
    value.includes("oracle") ||
    value.includes("mongodb") ||
    value.includes("mongo") ||
    value.includes("mssql")
  ) {
    return Database;
  }


  if (
    value.includes("redis") ||
    value.includes("cache")
  ) {
    return Zap;
  }


  if (
    value.includes("kafka") ||
    value.includes("rabbitmq") ||
    value.includes("queue") ||
    value.includes("message")
  ) {
    return MessageSquare;
  }


  if (
    value.includes("storage") ||
    value.includes("minio") ||
    value.includes("s3") ||
    value.includes("file")
  ) {
    return HardDrive;
  }


  if (
    value.includes("keycloak") ||
    value.includes("auth") ||
    value.includes("security") ||
    value.includes("identity")
  ) {
    return ShieldCheck;
  }


  if (
    value.includes("service") ||
    value.includes("microservice")
  ) {
    return Network;
  }


  if (
    value.includes("backend") ||
    value.includes("api") ||
    value.includes("fastapi") ||
    value.includes("flask") ||
    value.includes("express") ||
    value.includes("node") ||
    value.includes("java") ||
    value.includes("spring")
  ) {
    return Server;
  }


  if (
    value.includes("container") ||
    value.includes("docker") ||
    value.includes("pod") ||
    value.includes("kubernetes")
  ) {
    return Box;
  }


  if (
    value.includes("cloud") ||
    value.includes("aws") ||
    value.includes("azure") ||
    value.includes("gcp")
  ) {
    return Globe;
  }


  if (
    value.includes("compute") ||
    value.includes("worker")
  ) {
    return Cpu;
  }


  return AppWindow;
}


/* ============================================================
   CUSTOM APPLICATION NODE
   ============================================================ */

function ApplicationNode({ data }) {

  const Icon = getIcon(
    data.group,
    data.tech,
    data.label
  );


  return (
    <div className="application-map-node">

      <Handle
        type="target"
        position={Position.Left}
        className="application-map-handle"
      />


      <div className="application-map-node-header">

        <div className="application-map-icon">
          <Icon
            size={20}
            strokeWidth={1.8}
          />
        </div>


        <div
          className="application-map-title"
          title={data.label}
        >
          {data.label}
        </div>

      </div>


      <div className="application-map-body">

        {data.tech && (
          <div className="application-map-info">

            <span>
              Technology
            </span>

            <strong
              title={String(data.tech)}
            >
              {data.tech}
            </strong>

          </div>
        )}


        {data.port !== undefined &&
          data.port !== null &&
          data.port !== "" && (

            <div className="application-map-info">

              <span>
                Port
              </span>

              <strong>
                {data.port}
              </strong>

            </div>
          )}


        {data.host && (
          <div className="application-map-info">

            <span>
              Host
            </span>

            <strong
              title={String(data.host)}
            >
              {data.host}
            </strong>

          </div>
        )}


        <div className="application-map-group">

          {data.group ||
            "Application"}

        </div>

      </div>


      <Handle
        type="source"
        position={Position.Right}
        className="application-map-handle"
      />

    </div>
  );
}


/* ============================================================
   CREATE NODE
   ============================================================ */

function createNode(
  id,
  nodeData = {}
) {

  const data =
    nodeData &&
    typeof nodeData === "object"
      ? nodeData
      : {};


  return {

    id: normalizeId(id),

    type: "applicationNode",

    position: {
      x: 0,
      y: 0,
    },

    data: {

      id:
        normalizeId(id),

      originalId:
        id,

      label:
        data.label ||
        data.name ||
        id,

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
   FIND NODE NAME
   ============================================================ */

function findNodeName(
  text,
  nodeNames
) {

  const sortedNames =
    [...nodeNames].sort(
      (a, b) =>
        String(b).length -
        String(a).length
    );


  for (
    const name of sortedNames
  ) {

    const regex =
      new RegExp(
        `(^|\\s)${escapeRegex(name)}(?=\\s|$)`,
        "i"
      );


    if (
      regex.test(text)
    ) {
      return name;
    }

  }


  return null;
}


/* ============================================================
   PARSE STRING CONNECTION
   ============================================================

   Example:

   frontend alpha via HTTP on
   127.0.0.1:3000
   mig-test-lb...:8010

   =>

   frontend -> alpha

   ============================================================ */

function parseStringConnection(
  connection,
  nodeNames
) {

  const text =
    cleanText(connection);


  if (!text) {
    return null;
  }


  const viaIndex =
    text
      .toLowerCase()
      .indexOf(" via ");


  if (viaIndex === -1) {
    return null;
  }


  const applicationPart =
    text
      .substring(
        0,
        viaIndex
      )
      .trim();


  const sourceNode =
    findNodeName(
      applicationPart,
      nodeNames
    );


  if (!sourceNode) {
    return null;
  }


  const sourceRegex =
    new RegExp(
      `^${escapeRegex(sourceNode)}\\s*`,
      "i"
    );


  const remaining =
    applicationPart
      .replace(
        sourceRegex,
        ""
      )
      .trim();


  const targetNode =
    findNodeName(
      remaining,
      nodeNames
    );


  if (!targetNode) {
    return null;
  }


  const protocolMatch =
    text.match(
      /\s+via\s+([^\s]+)/i
    );


  const protocol =
    protocolMatch
      ? protocolMatch[1]
      : "";


  return {

    from:
      sourceNode,

    to:
      targetNode,

    protocol,

    label:
      protocol
        ? protocol.toUpperCase()
        : "",

    raw:
      text,

  };
}


/* ============================================================
   PARSE API RESPONSE
   ============================================================ */

function parseResponse(
  apiResponse
) {

  const nodeMap =
    new Map();

  const rawConnections =
    [];


  if (
    !Array.isArray(
      apiResponse
    )
  ) {

    return {
      nodes: [],
      edges: [],
    };

  }


  /* ==========================================================
     STEP 1
     COLLECT ALL NODES FIRST
     ========================================================== */

  apiResponse.forEach(
    (record) => {

      if (
        !record ||
        typeof record !==
          "object"
      ) {
        return;
      }


      const recommendation =
        record.recommendation ||
        {};


      const nodes =
        recommendation.Nodes ||
        recommendation.nodes ||
        {};


      if (
        !nodes ||
        typeof nodes !==
          "object" ||
        Array.isArray(nodes)
      ) {
        return;
      }


      Object.entries(
        nodes
      ).forEach(
        ([nodeId, nodeData]) => {

          const normalized =
            normalizeId(
              nodeId
            );


          if (!normalized) {
            return;
          }


          if (
            nodeMap.has(
              normalized
            )
          ) {

            const existing =
              nodeMap.get(
                normalized
              );


            nodeMap.set(
              normalized,
              {
                ...existing,

                data: {
                  ...existing.data,
                  ...(nodeData || {}),
                },
              }
            );

          } else {

            nodeMap.set(
              normalized,
              createNode(
                nodeId,
                nodeData
              )
            );

          }

        }
      );

    }
  );


  /* ==========================================================
     STEP 2
     COLLECT CONNECTIONS
     ========================================================== */

  apiResponse.forEach(
    (record) => {

      if (
        !record ||
        typeof record !==
          "object"
      ) {
        return;
      }


      const recommendation =
        record.recommendation ||
        {};


      const connections =
        recommendation.Connections ||
        recommendation.connections ||
        [];


      if (
        !Array.isArray(
          connections
        )
      ) {
        return;
      }


      connections.forEach(
        (connection) => {

          if (!connection) {
            return;
          }


          /*
           * Object format:
           *
           * {
           *   from: "frontend",
           *   to: "alpha"
           * }
           */

          if (
            typeof connection ===
            "object"
          ) {

            const from =
              connection.from ||
              connection.source;

            const to =
              connection.to ||
              connection.target;


            if (!from || !to) {
              return;
            }


            rawConnections.push({

              from:
                String(
                  from
                ).trim(),

              to:
                String(
                  to
                ).trim(),

              protocol:
                connection.protocol ||
                connection.type ||
                "",

              label:
                connection.label ||
                connection.protocol ||
                "",

              raw:
                connection,

            });


            return;
          }


          /*
           * String format.
           */

          if (
            typeof connection ===
            "string"
          ) {

            rawConnections.push(
              connection
            );

          }

        }
      );

    }
  );


  /* ==========================================================
     STEP 3
     GET ACTUAL NODE NAMES
     ========================================================== */

  const nodeNames =
    Array.from(
      nodeMap.values()
    ).map(
      (node) =>
        node.data.originalId
    );


  /* ==========================================================
     STEP 4
     BUILD EDGES
     ========================================================== */

  const edges =
    [];

  const edgeKeys =
    new Set();


  rawConnections.forEach(
    (
      connection,
      index
    ) => {

      let parsed;


      /*
       * Object connection
       */

      if (
        typeof connection ===
        "object"
      ) {

        parsed = {
          ...connection,

          from:
            String(
              connection.from
            ).trim(),

          to:
            String(
              connection.to
            ).trim(),
        };

      }


      /*
       * String connection
       */

      else {

        parsed =
          parseStringConnection(
            connection,
            nodeNames
          );

      }


      if (!parsed) {

        console.warn(
          "Unable to parse mapping connection:",
          connection
        );

        return;
      }


      const source =
        normalizeId(
          parsed.from
        );

      const target =
        normalizeId(
          parsed.to
        );


      if (
        !source ||
        !target
      ) {
        return;
      }


      /*
       * Ignore invalid references.
       */

      if (
        !nodeMap.has(
          source
        ) ||
        !nodeMap.has(
          target
        )
      ) {

        console.warn(
          "Mapping connection references unknown node:",
          parsed.from,
          parsed.to
        );

        return;
      }


      const edgeKey =
        `${source}->${target}`;


      /*
       * Prevent duplicate edges.
       */

      if (
        edgeKeys.has(
          edgeKey
        )
      ) {
        return;
      }


      edgeKeys.add(
        edgeKey
      );


      edges.push({

        id:
          `mapping-edge-${source}-${target}-${index}`,

        source,

        target,

        type:
          "smoothstep",

        animated:
          true,

        markerEnd: {
          type:
            MarkerType.ArrowClosed,
        },

        label:
          parsed.label ||
          parsed.protocol ||
          "",

        style: {
          strokeWidth: 2,
        },

        labelStyle: {
          fontSize: 10,
          fontWeight: 500,
        },

        labelBgStyle: {
          fill: "#ffffff",
        },

        labelBgPadding:
          [4, 2],

        labelBgBorderRadius:
          3,

      });

    }
  );


  return {

    nodes:
      Array.from(
        nodeMap.values()
      ),

    edges,

  };
}


/* ============================================================
   GRAPH LAYOUT
   ============================================================ */

function layoutGraph(
  nodes,
  edges
) {

  if (
    !nodes.length
  ) {
    return [];
  }


  const incoming =
    new Map();

  const outgoing =
    new Map();


  nodes.forEach(
    (node) => {

      incoming.set(
        node.id,
        []
      );

      outgoing.set(
        node.id,
        []
      );

    }
  );


  edges.forEach(
    (edge) => {

      if (
        outgoing.has(
          edge.source
        )
      ) {

        outgoing
          .get(edge.source)
          .push(
            edge.target
          );

      }


      if (
        incoming.has(
          edge.target
        )
      ) {

        incoming
          .get(edge.target)
          .push(
            edge.source
          );

      }

    }
  );


  /*
   * Find root nodes.
   */

  let roots =
    nodes.filter(
      (node) =>
        incoming
          .get(node.id)
          .length === 0
    );


  /*
   * If the graph has only cycles,
   * start from the first node.
   */

  if (
    roots.length === 0
  ) {

    roots = [
      nodes[0],
    ];

  }


  const levels =
    new Map();

  const queue =
    [];


  roots.forEach(
    (root) => {

      if (
        !levels.has(
          root.id
        )
      ) {

        levels.set(
          root.id,
          0
        );

        queue.push(
          root.id
        );

      }

    }
  );


  /*
   * BFS.
   */

  while (
    queue.length
  ) {

    const current =
      queue.shift();


    const currentLevel =
      levels.get(
        current
      ) || 0;


    const children =
      outgoing.get(
        current
      ) || [];


    children.forEach(
      (child) => {

        if (
          !levels.has(
            child
          )
        ) {

          levels.set(
            child,
            currentLevel + 1
          );

          queue.push(
            child
          );

        }

      }
    );

  }


  /*
   * Nodes not connected to the
   * discovered graph.
   */

  let maxLevel =
    0;


  levels.forEach(
    (level) => {

      maxLevel =
        Math.max(
          maxLevel,
          level
        );

    }
  );


  nodes.forEach(
    (node) => {

      if (
        !levels.has(
          node.id
        )
      ) {

        levels.set(
          node.id,
          maxLevel + 1
        );

      }

    }
  );


  /*
   * Group nodes by level.
   */

  const columns =
    new Map();


  nodes.forEach(
    (node) => {

      const level =
        levels.get(
          node.id
        ) || 0;


      if (
        !columns.has(
          level
        )
      ) {

        columns.set(
          level,
          []
        );

      }


      columns
        .get(level)
        .push(node);

    }
  );


  /*
   * Sort nodes by group.
   */

  columns.forEach(
    (column) => {

      column.sort(
        (a, b) =>
          String(
            a.data.group || ""
          ).localeCompare(
            String(
              b.data.group || ""
            )
          )
      );

    }
  );


  /*
   * Position.
   */

  const horizontalGap =
    360;

  const verticalGap =
    190;


  const result =
    [];


  Array.from(
    columns.entries()
  )
    .sort(
      ([a], [b]) =>
        a - b
    )
    .forEach(
      (
        [level, column]
      ) => {

        const columnHeight =
          (column.length - 1) *
          verticalGap;


        column.forEach(
          (
            node,
            index
          ) => {

            result.push({

              ...node,

              position: {

                x:
                  level *
                  horizontalGap,

                y:
                  index *
                    verticalGap -
                  columnHeight /
                    2 +
                  350,

              },

            });

          }
        );

      }
    );


  return result;
}


/* ============================================================
   MAIN MAPPING COMPONENT
   ============================================================ */

function MappingDiagram({
  source,
  apiUrl = API_URL,
}) {

  const [
    nodes,
    setNodes,
    onNodesChange,
  ] =
    useNodesState([]);


  const [
    edges,
    setEdges,
    onEdgesChange,
  ] =
    useEdgesState([]);


  const [
    loading,
    setLoading,
  ] =
    useState(false);


  const [
    error,
    setError,
  ] =
    useState("");


  const [
    selectedNode,
    setSelectedNode,
  ] =
    useState(null);


  const nodeTypes =
    useMemo(
      () => ({
        applicationNode:
          ApplicationNode,
      }),
      []
    );


  /* ==========================================================
     LOAD MAPPING
     ========================================================== */

  const loadMapping =
    useCallback(
      async () => {

        setLoading(
          true
        );

        setError("");


        try {

          const response =
            await fetch(
              apiUrl,
              {
                method:
                  "POST",

                headers: {
                  "Content-Type":
                    "application/json",
                },

                body:
                  JSON.stringify({
                    source:
                      source,
                  }),

              }
            );


          if (
            !response.ok
          ) {

            throw new Error(
              `Mapping API returned HTTP ${response.status}`
            );

          }


          const data =
            await response.json();


          console.log(
            "Application mapping API response:",
            data
          );


          const parsed =
            parseResponse(
              data
            );


          console.log(
            "Parsed mapping nodes:",
            parsed.nodes
          );


          console.log(
            "Parsed mapping edges:",
            parsed.edges
          );


          const positionedNodes =
            layoutGraph(
              parsed.nodes,
              parsed.edges
            );


          setNodes(
            positionedNodes
          );

          setEdges(
            parsed.edges
          );

        } catch (
          err
        ) {

          console.error(
            "Application mapping error:",
            err
          );


          setError(
            err?.message ||
              "Failed to load application mapping."
          );

        } finally {

          setLoading(
            false
          );

        }

      },
      [
        source,
        apiUrl,
        setNodes,
        setEdges,
      ]
    );


  /* ==========================================================
     LOAD WHEN SOURCE CHANGES
     ========================================================== */

  useEffect(
    () => {

      loadMapping();

    },
    [loadMapping]
  );


  /* ==========================================================
     NODE CLICK
     ========================================================== */

  const onNodeClick =
    useCallback(
      (_, node) => {

        setSelectedNode(
          node
        );

      },
      []
    );


  return (
    <div
      className="application-mapping-container"
    >

      {/* ======================================================
          HEADER
         ====================================================== */}

      <div
        className="application-mapping-header"
      >

        <div>

          <div
            className="application-mapping-heading"
          >
            Application Mapping
          </div>


          <div
            className="application-mapping-count"
          >

            {nodes.length}
            {" "}
            components

            {" · "}

            {edges.length}
            {" "}
            connections

          </div>

        </div>


        <button
          type="button"
          onClick={
            loadMapping
          }
          disabled={
            loading
          }
          className="application-mapping-refresh"
        >

          <RefreshCw
            size={14}
            className={
              loading
                ? "application-mapping-spin"
                : ""
            }
          />

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
          className="application-mapping-error"
        >

          <strong>
            Mapping API Error
          </strong>

          <div>
            {error}
          </div>

        </div>

      )}


      {/* ======================================================
          GRAPH
         ====================================================== */}

      <div
        className="application-mapping-graph"
      >

        {loading &&
          nodes.length === 0 && (

            <div
              className="application-mapping-loading"
            >
              Loading application mapping...
            </div>

          )}


        {!loading &&
          !error &&
          nodes.length === 0 && (

            <div
              className="application-mapping-empty"
            >
              No application components
              were found.
            </div>

          )}


        <ReactFlow
          nodes={
            nodes
          }

          edges={
            edges
          }

          nodeTypes={
            nodeTypes
          }

          onNodesChange={
            onNodesChange
          }

          onEdgesChange={
            onEdgesChange
          }

          onNodeClick={
            onNodeClick
          }

          fitView

          fitViewOptions={{
            padding:
              0.25,

            minZoom:
              0.1,

            maxZoom:
              1.2,
          }}

          minZoom={
            0.08
          }

          maxZoom={
            2
          }

          nodesConnectable={
            false
          }

          nodesDraggable={
            true
          }

          elementsSelectable={
            true
          }

          proOptions={{
            hideAttribution:
              true,
          }}
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
          NODE DETAILS
         ====================================================== */}

      {selectedNode && (

        <div
          className="application-mapping-details"
        >

          <div
            className="application-mapping-details-header"
          >

            <span>
              {
                selectedNode
                  .data
                  ?.label ||
                selectedNode.id
              }
            </span>


            <button
              type="button"
              onClick={() =>
                setSelectedNode(
                  null
                )
              }
            >

              <X
                size={16}
              />

            </button>

          </div>


          <div
            className="application-mapping-details-body"
          >

            <DetailRow
              label="Node"
              value={
                selectedNode
                  .data
                  ?.originalId
              }
            />


            <DetailRow
              label="Technology"
              value={
                selectedNode
                  .data
                  ?.tech
              }
            />


            <DetailRow
              label="Group"
              value={
                selectedNode
                  .data
                  ?.group
              }
            />


            <DetailRow
              label="Host"
              value={
                selectedNode
                  .data
                  ?.host
              }
            />


            <DetailRow
              label="Port"
              value={
                selectedNode
                  .data
                  ?.port
              }
            />


            {selectedNode
              .data
              ?.description && (

              <DetailRow
                label="Description"
                value={
                  selectedNode
                    .data
                    ?.description
                }
              />

            )}

          </div>

        </div>

      )}


      {/* ======================================================
          COMPONENT STYLES
         ====================================================== */}

      <style jsx global>{`

        .application-mapping-container {
          width: 100%;
          height: 750px;
          position: relative;
          background: #f8fafc;
          border: 1px solid #dbe3ec;
          border-radius: 10px;
          overflow: hidden;
        }


        .application-mapping-header {
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 15px;
          background: #ffffff;
          border-bottom: 1px solid #e2e8f0;
          position: relative;
          z-index: 10;
        }


        .application-mapping-heading {
          font-size: 15px;
          font-weight: 600;
          color: #172033;
        }


        .application-mapping-count {
          margin-top: 2px;
          font-size: 11px;
          color: #64748b;
        }


        .application-mapping-refresh {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 7px 11px;
          border: 1px solid #cbd5e1;
          border-radius: 6px;
          background: #ffffff;
          color: #334155;
          font-size: 12px;
          cursor: pointer;
        }


        .application-mapping-refresh:hover {
          background: #f8fafc;
        }


        .application-mapping-refresh:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }


        .application-mapping-spin {
          animation: applicationMappingSpin 1s linear infinite;
        }


        @keyframes applicationMappingSpin {
          from {
            transform: rotate(0deg);
          }

          to {
            transform: rotate(360deg);
          }
        }


        .application-mapping-graph {
          position: absolute;
          top: 56px;
          left: 0;
          right: 0;
          bottom: 0;
        }


        .application-mapping-loading,
        .application-mapping-empty {
          position: absolute;
          z-index: 20;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #64748b;
          font-size: 13px;
          pointer-events: none;
        }


        .application-mapping-loading {
          background: rgba(248, 250, 252, 0.75);
        }


        .application-mapping-empty {
          background: #f8fafc;
        }


        .application-mapping-error {
          position: absolute;
          z-index: 50;
          top: 70px;
          left: 15px;
          right: 15px;
          padding: 11px 13px;
          background: #fef2f2;
          border: 1px solid #fecaca;
          border-radius: 7px;
          color: #991b1b;
          font-size: 12px;
        }


        .application-mapping-error strong {
          display: block;
          margin-bottom: 3px;
        }


        /* ======================================================
           APPLICATION NODE
           ====================================================== */

        .application-map-node {
          width: 245px;
          min-height: 115px;
          background: #ffffff;
          border: 1px solid #cbd5e1;
          border-radius: 9px;
          box-shadow: 0 3px 12px rgba(15, 23, 42, 0.08);
          overflow: visible;
        }


        .application-map-node:hover {
          border-color: #94a3b8;
          box-shadow: 0 5px 18px rgba(15, 23, 42, 0.12);
        }


        .application-map-node-header {
          display: flex;
          align-items: center;
          gap: 9px;
          padding: 10px 11px;
          border-bottom: 1px solid #e2e8f0;
          background: #f8fafc;
          border-radius: 9px 9px 0 0;
        }


        .application-map-icon {
          width: 34px;
          height: 34px;
          flex-shrink: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid #dbe3ec;
          border-radius: 7px;
          background: #ffffff;
          color: #475569;
        }


        .application-map-title {
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 13px;
          font-weight: 600;
          color: #172033;
        }


        .application-map-body {
          padding: 8px 11px 10px;
        }


        .application-map-info {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 8px;
          padding: 3px 0;
          font-size: 10px;
        }


        .application-map-info span {
          color: #64748b;
          flex-shrink: 0;
        }


        .application-map-info strong {
          max-width: 155px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          text-align: right;
          color: #334155;
          font-weight: 500;
        }


        .application-map-group {
          display: inline-block;
          margin-top: 6px;
          padding: 3px 7px;
          border-radius: 4px;
          background: #f1f5f9;
          color: #475569;
          font-size: 9px;
          font-weight: 600;
        }


        .application-map-handle {
          width: 8px;
          height: 8px;
          background: #64748b;
          border: 2px solid #ffffff;
        }


        /* ======================================================
           DETAILS PANEL
           ====================================================== */

        .application-mapping-details {
          position: absolute;
          z-index: 100;
          top: 70px;
          right: 15px;
          width: 290px;
          max-height: calc(100% - 90px);
          overflow: auto;
          background: #ffffff;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          box-shadow: 0 8px 25px rgba(15, 23, 42, 0.15);
        }


        .application-mapping-details-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 11px 13px;
          border-bottom: 1px solid #e2e8f0;
          font-size: 13px;
          font-weight: 600;
          color: #172033;
        }


        .application-mapping-details-header span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }


        .application-mapping-details-header button {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 26px;
          height: 26px;
          border: none;
          border-radius: 5px;
          background: transparent;
          color: #64748b;
          cursor: pointer;
        }


        .application-mapping-details-header button:hover {
          background: #f1f5f9;
        }


        .application-mapping-details-body {
          padding: 9px 13px 12px;
        }


        .application-mapping-detail-row {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 10px;
          padding: 7px 0;
          border-bottom: 1px solid #f1f5f9;
          font-size: 11px;
        }


        .application-mapping-detail-row:last-child {
          border-bottom: none;
        }


        .application-mapping-detail-label {
          color: #64748b;
          flex-shrink: 0;
        }


        .application-mapping-detail-value {
          max-width: 175px;
          color: #334155;
          font-weight: 500;
          text-align: right;
          word-break: break-word;
        }


        /* ======================================================
           REACT FLOW OVERRIDES
           ====================================================== */

        .react-flow__edge-text {
          font-size: 10px;
          font-weight: 500;
        }


        .react-flow__controls {
          box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
          border: 1px solid #dbe3ec;
        }


        .react-flow__controls-button {
          width: 30px;
          height: 30px;
          background: #ffffff;
          border-bottom: 1px solid #e2e8f0;
        }


        .react-flow__minimap {
          border: 1px solid #dbe3ec;
          box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
        }

      `}</style>

    </div>
  );
}


/* ============================================================
   DETAIL ROW
   ============================================================ */

function DetailRow({
  label,
  value,
}) {

  return (
    <div
      className="application-mapping-detail-row"
    >

      <span
        className="application-mapping-detail-label"
      >
        {label}
      </span>


      <strong
        className="application-mapping-detail-value"
      >
        {value !== undefined &&
        value !== null &&
        value !== ""
          ? String(value)
          : "Unknown"}
      </strong>

    </div>
  );
}


/* ============================================================
   EXPORTED COMPONENT
   ============================================================ */

export default function AppArchitectureDiagram({
  source,
  apiUrl = API_URL,
}) {

  return (
    <ReactFlowProvider>

      <MappingDiagram
        source={source}
        apiUrl={apiUrl}
      />

    </ReactFlowProvider>
  );
}

Install the dependencies if needed:

npm install @xyflow/react lucide-react

Use it like:

<AppArchitectureDiagram source={source} />

The request sent to your API is:

{
  "source": "your source value"
}

One important point: do not put the "Connections" parsing in the frontend if you can change your backend. The ideal API response is still:

"Connections": [
  {
    "from": "frontend",
    "to": "alpha",
    "protocol": "HTTP"
  },
  {
    "from": "frontend",
    "to": "gamma",
    "protocol": "HTTP"
  }
]

But the file above supports both that format and your current string format, so your current API response should produce visible edges.
