import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Cloud,
  Container,
  LoaderCircle,
  RefreshCw,
  Server,
  ArrowRight,
  AlertCircle,
  Boxes,
  Code2,
} from "lucide-react";

import useSourceCredentialStore from "../../store/sourceCredentialStore";
import useRunStore from "../../store/runStore";
import { axiosDiscoveryTool } from "../../../../services/axios.instance.service";
import RunStep from "./RunStep";

const API = {
  sourceContainers: "/api/get-containers",
  sourceNonContainers: "/api/get-source-non-container",
  targetContainers: "/api/get-target-containers",
  targetNonContainers: "/api/get-target-non-container",
  testTarget: "/api/test_ssh",

  migrateContainer: "/api/shift-single",
  migrateNonContainer: "/api/non-container-shift-single",

  containerizeNonContainer:
    "/api/non-container-to-container-migrate",

  migrateToCloud:
    "/api/cloud-container-migration/migrate-to-ecs",
};

const panelStyle = {
  border: "1px solid #dce2ea",
  borderRadius: 12,
  background: "#fff",
  minWidth: 0,
  overflow: "hidden",
};

const panelHeaderStyle = {
  padding: "14px 16px",
  borderBottom: "1px solid #e8edf3",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const fieldStyle = {
  width: "100%",
  boxSizing: "border-box",
  border: "1px solid #cfd7e3",
  borderRadius: 7,
  padding: "9px 10px",
  background: "#fff",
  color: "#1f2937",
};

const buttonStyle = {
  border: 0,
  borderRadius: 7,
  padding: "8px 11px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

const primaryButton = {
  ...buttonStyle,
  color: "#fff",
  background: "#e87524",
};

const secondaryButton = {
  ...buttonStyle,
  color: "#263244",
  background: "#edf1f6",
};

function Spinner({ label = "Loading..." }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        color: "#687386",
        padding: "12px 0",
      }}
    >
      <LoaderCircle
        size={17}
        className="transfer-spin"
        aria-hidden="true"
      />

      <span>{label}</span>

      <style>
        {`
          .transfer-spin {
            animation: transfer-spin 1s linear infinite;
          }

          @keyframes transfer-spin {
            to {
              transform: rotate(360deg);
            }
          }
        `}
      </style>
    </div>
  );
}

function EmptyState({ children }) {
  return (
    <div
      style={{
        color: "#778195",
        padding: "18px 10px",
        textAlign: "center",
        fontSize: 13,
      }}
    >
      {children}
    </div>
  );
}

function getAppName(item) {
  return (
    item?.name ||
    item?.container_name ||
    item?.app_name ||
    item?.application ||
    item?.process_name ||
    item?.pid ||
    "Unnamed application"
  );
}

function getContainerId(item) {
  return (
    item?.container_id ||
    item?.id ||
    item?.containerId ||
    item?.name
  );
}

function getHostPort(item) {
  return (
    item?.host_port ??
    item?.hostPort ??
    item?.port ??
    ""
  );
}

function getContainerPort(item) {
  return (
    item?.container_port ??
    item?.containerPort ??
    item?.port ??
    ""
  );
}

function getImage(item) {
  return (
    item?.img ||
    item?.image ||
    item?.image_name ||
    ""
  );
}

/*
 * PCF is detected from the API response.
 *
 * Nothing is hardcoded for a particular application name.
 */
function isPcfApp(item) {
  const values = [
    item?.name,
    item?.tech,
    item?.tech_stack,
    item?.technology,
    item?.framework,
    item?.type,
    item?.application_type,
    item?.process_name,
  ];

  return values.some(
    (value) =>
      typeof value === "string" &&
      /\bpcf\b|pivotal cloud foundry|cloud foundry/i.test(
        value
      )
  );
}

export default function TransferStep({
  setStep,
  source,
  test_connection,
  summary,
  setRunStep,
}) {
  const { sourceCredential } =
    useSourceCredentialStore();

  const { existingRunId } =
    useRunStore();

  /*
   * ============================================================
   * CATEGORY
   * ============================================================
   */

  const [activeCategory, setActiveCategory] =
    useState("container");

  /*
   * ============================================================
   * TARGET VM
   * ============================================================
   */

  const [targetVm, setTargetVm] = useState({
    ip: "",
    TargetUsername: "",
    TargetPassword: "",
    TargetSudoPassword: "",
  });

  const [targetStatus, setTargetStatus] =
    useState("disconnected");

  const [targetError, setTargetError] =
    useState("");

  /*
   * ============================================================
   * SOURCE DATA
   * ============================================================
   */

  const [sourceContainers, setSourceContainers] =
    useState([]);

  const [sourceNonContainers, setSourceNonContainers] =
    useState([]);

  /*
   * ============================================================
   * TARGET DATA
   * ============================================================
   */

  const [targetContainers, setTargetContainers] =
    useState([]);

  const [targetNonContainers, setTargetNonContainers] =
    useState([]);

  /*
   * ============================================================
   * LOADING
   * ============================================================
   */

  const [sourceLoading, setSourceLoading] =
    useState({
      container: true,
      nonContainer: true,
    });

  const [targetLoading, setTargetLoading] =
    useState({
      container: false,
      nonContainer: false,
    });

  const [sourceErrors, setSourceErrors] =
    useState({});

  const [targetErrors, setTargetErrors] =
    useState({});

  /*
   * ============================================================
   * COMMON OPERATION STATE
   * ============================================================
   */

  const [busyKey, setBusyKey] =
    useState("");

  const [notice, setNotice] =
    useState(null);

  /*
   * ============================================================
   * CONTAINERIZED APPLICATIONS
   *
   * Used for:
   * - Non-container -> Container
   * - Future PCF -> Container
   * ============================================================
   */

  const [containerizedPcf, setContainerizedPcf] =
    useState({});

  /*
   * ============================================================
   * CLOUD MIGRATION
   * ============================================================
   */

  const [cloudStatuses, setCloudStatuses] =
    useState({});

  const [cloudFormFor, setCloudFormFor] =
    useState(null);

  const [cloudForm, setCloudForm] =
    useState({
      imageTag: "v1",
      ecsService: "",
      taskFamily: "",
      containerName: "",
      taskCpu: "512",
      taskMemory: "1024",
      subnet: "",
      securityGroup: "",
      ecrRepository: "atm-migrated-apps",
      awsRegion: "ap-south-1",
    });

  /*
   * ============================================================
   * RUN STEP
   * ============================================================
   */

  const [applicationStatus, setApplicationStatus] =
    useState(null);

  const [showRunStep, setShowRunStep] =
    useState(false);

  /*
   * ============================================================
   * SOURCE CREDENTIAL
   * ============================================================
   */

  const sourceCred =
    sourceCredential || source || {};

  const sourcePayload = useMemo(
    () => ({
      source: sourceCred,
    }),
    [sourceCred]
  );

  /*
   * ============================================================
   * SOURCE CONTAINER DISCOVERY
   * ============================================================
   */

  const fetchSourceContainers =
    useCallback(async () => {
      setSourceLoading((state) => ({
        ...state,
        container: true,
      }));

      setSourceErrors((state) => ({
        ...state,
        container: "",
      }));

      try {
        const { data } =
          await axiosDiscoveryTool.post(
            API.sourceContainers,
            sourcePayload
          );

        setSourceContainers(
          Array.isArray(data?.containers)
            ? data.containers
            : []
        );
      } catch (error) {
        setSourceErrors((state) => ({
          ...state,
          container:
            error?.response?.data?.message ||
            error?.message ||
            "Unable to load source containers.",
        }));
      } finally {
        setSourceLoading((state) => ({
          ...state,
          container: false,
        }));
      }
    }, [sourcePayload]);

  /*
   * ============================================================
   * SOURCE NON-CONTAINER DISCOVERY
   * ============================================================
   */

  const fetchSourceNonContainers =
    useCallback(async () => {
      setSourceLoading((state) => ({
        ...state,
        nonContainer: true,
      }));

      setSourceErrors((state) => ({
        ...state,
        nonContainer: "",
      }));

      try {
        const { data } =
          await axiosDiscoveryTool.post(
            API.sourceNonContainers,
            sourcePayload
          );

        setSourceNonContainers(
          Array.isArray(
            data?.source_non_containerized
          )
            ? data.source_non_containerized
            : []
        );
      } catch (error) {
        setSourceErrors((state) => ({
          ...state,
          nonContainer:
            error?.response?.data?.message ||
            error?.message ||
            "Unable to load source applications.",
        }));
      } finally {
        setSourceLoading((state) => ({
          ...state,
          nonContainer: false,
        }));
      }
    }, [sourcePayload]);

  /*
   * ============================================================
   * AUTOMATIC SOURCE DISCOVERY
   *
   * No button is required.
   * ============================================================
   */

  useEffect(() => {
    if (
      !sourceCred?.host &&
      !sourceCred?.ip
    ) {
      setSourceLoading({
        container: false,
        nonContainer: false,
      });

      setSourceErrors({
        container:
          "Source credentials are not available. Complete source discovery first.",

        nonContainer:
          "Source credentials are not available. Complete source discovery first.",
      });

      return;
    }

    fetchSourceContainers();
    fetchSourceNonContainers();
  }, [
    sourceCred?.host,
    sourceCred?.ip,
    fetchSourceContainers,
    fetchSourceNonContainers,
  ]);

  /*
   * ============================================================
   * TARGET APPLICATION DISCOVERY
   * ============================================================
   */

  const fetchTargetApplications =
    useCallback(async () => {
      setTargetLoading({
        container: true,
        nonContainer: true,
      });

      setTargetErrors({});

      try {
        const [
          containersResult,
          appsResult,
        ] = await Promise.allSettled([
          axiosDiscoveryTool.post(
            API.targetContainers,
            {
              target: targetVm,
            }
          ),

          axiosDiscoveryTool.post(
            API.targetNonContainers,
            {
              target: targetVm,
            }
          ),
        ]);

        /*
         * TARGET CONTAINERS
         */

        if (
          containersResult.status ===
          "fulfilled"
        ) {
          const data =
            containersResult.value.data;

          setTargetContainers(
            Array.isArray(data?.containers)
              ? data.containers
              : []
          );
        } else {
          setTargetErrors((state) => ({
            ...state,

            container:
              containersResult.reason
                ?.response?.data?.message ||
              containersResult.reason
                ?.message ||
              "Unable to load target containers.",
          }));
        }

        /*
         * TARGET NON-CONTAINERS
         */

        if (
          appsResult.status ===
          "fulfilled"
        ) {
          const data =
            appsResult.value.data;

          setTargetNonContainers(
            Array.isArray(
              data?.target_non_containerized
            )
              ? data.target_non_containerized
              : []
          );
        } else {
          setTargetErrors((state) => ({
            ...state,

            nonContainer:
              appsResult.reason
                ?.response?.data?.message ||
              appsResult.reason?.message ||
              "Unable to load target applications.",
          }));
        }
      } finally {
        setTargetLoading({
          container: false,
          nonContainer: false,
        });
      }
    }, [targetVm]);

  /*
   * ============================================================
   * TARGET CONNECTION
   * ============================================================
   */

  async function connectTarget() {
    setTargetStatus("connecting");
    setTargetError("");
    setNotice(null);

    try {
      await axiosDiscoveryTool.post(
        API.testTarget,
        {
          host: targetVm.ip,
          user: targetVm.TargetUsername,
          password:
            targetVm.TargetPassword,
          sudo_password:
            targetVm.TargetSudoPassword,
        },
        {
          headers: {
            "Content-Type":
              "application/json",
          },
        }
      );

      setTargetStatus("connected");

      localStorage.setItem(
        "targetVm",
        JSON.stringify(targetVm)
      );

      setNotice({
        type: "success",
        text:
          "Target connected. Loading target applications…",
      });

      await fetchTargetApplications();
    } catch (error) {
      setTargetStatus("error");

      setTargetError(
        error?.response?.data?.message ||
          error?.message ||
          "Target connection failed."
      );
    }
  }

  /*
   * ============================================================
   * EXTERNAL TEST CONNECTION SIGNAL
   * ============================================================
   */

  useEffect(() => {
    if (test_connection) {
      connectTarget();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [test_connection]);

  /*
   * ============================================================
   * RESTORE TARGET VM
   * ============================================================
   */

  useEffect(() => {
    try {
      const stored =
        localStorage.getItem(
          "targetVm"
        );

      if (stored) {
        const parsed =
          JSON.parse(stored);

        setTargetVm((current) => ({
          ...current,
          ...parsed,
        }));
      }
    } catch {
      // Ignore invalid localStorage data.
    }
  }, []);

  const targetConnected =
    targetStatus === "connected";

  /*
   * ============================================================
   * CONTAINER -> TARGET VM
   * ============================================================
   */

  async function migrateContainerToVm(
    item
  ) {
    const name = getAppName(item);

    const key =
      `container:${getContainerId(item)}`;

    setBusyKey(key);
    setNotice(null);

    try {
      const { data } =
        await axiosDiscoveryTool.post(
          API.migrateContainer,
          {
            runid: existingRunId,

            userName:
              localStorage.getItem(
                "userName"
              ),

            groupName:
              localStorage.getItem(
                "groupName"
              ),

            name,

            img: getImage(item),

            host:
              getHostPort(item),

            container_port:
              getContainerPort(item),

            source: sourceCred,

            target: targetVm,
          }
        );

      setNotice({
        type: "success",
        text:
          data?.message ||
          `Container "${name}" migration request completed.`,
      });

      await fetchTargetApplications();
    } catch (error) {
      setNotice({
        type: "error",
        text:
          error?.response?.data?.message ||
          error?.message ||
          `Failed to migrate "${name}".`,
      });
    } finally {
      setBusyKey("");
    }
  }

  /*
   * ============================================================
   * NON-CONTAINER -> TARGET VM
   * ============================================================
   */

  async function migrateNonContainer(
    item
  ) {
    const pid = item?.pid;

    const local =
      getHostPort(item);

    const tech =
      item?.tech_stack ||
      item?.tech ||
      item?.technology ||
      "";

    const key =
      `app:${pid ?? getAppName(item)}`;

    setBusyKey(key);
    setNotice(null);

    try {
      const { data } =
        await axiosDiscoveryTool.post(
          API.migrateNonContainer,
          {
            runid: existingRunId,

            name:
              localStorage.getItem(
                "userName"
              ),

            groupName:
              localStorage.getItem(
                "groupName"
              ),

            local,
            tech,
            pid,

            source: sourceCred,

            target: targetVm,
          }
        );

      setNotice({
        type: "success",
        text:
          data?.message ||
          `Application "${getAppName(
            item
          )}" migration request completed.`,
      });

      if (
        data?.non_containerized_res ||
        data?.run_command_non_container
      ) {
        setApplicationStatus({
          name: getAppName(item),
          port: local,
          isContainer: false,
          ...data,
        });
      }

      await fetchTargetApplications();
    } catch (error) {
      setNotice({
        type: "error",
        text:
          error?.response?.data?.message ||
          error?.message ||
          `Failed to migrate "${getAppName(
            item
          )}".`,
      });
    } finally {
      setBusyKey("");
    }
  }

  /*
   * ============================================================
   * PCF -> CONTAINER
   *
   * PLACEHOLDER ONLY
   *
   * API will be added later.
   * ============================================================
   */

  async function makePcfApplicationContainer(
    item
  ) {
    setBusyKey(
      `pcf:${item?.pid ?? getAppName(item)}`
    );

    setNotice({
      type: "info",
      text:
        "PCF containerization API is not wired yet. The placeholder function is ready for that integration.",
    });

    try {
      /*
       * TODO:
       *
       * When the PCF containerization API
       * is available, add it here.
       *
       * Example:
       *
       * const { data } =
       *   await axiosDiscoveryTool.post(
       *     "/api/pcf-to-container",
       *     {
       *       application: item,
       *       source: sourceCred
       *     }
       *   );
       *
       * setContainerizedPcf(
       *   current => ({
       *     ...current,
       *     [item.pid]:
       *       data.container
       *   })
       * );
       */
    } finally {
      setBusyKey("");
    }
  }

  /*
   * ============================================================
   * MIGRATE CREATED PCF CONTAINER
   * ============================================================
   */

  async function migratePcfContainer(
    item
  ) {
    const container =
      containerizedPcf[item?.pid];

    if (!container) {
      return;
    }

    await migrateContainerToVm(
      container
    );
  }

  /*
   * ============================================================
   * OPEN CLOUD MIGRATION FORM
   * ============================================================
   */

  function startCloudMigration(item) {
    setCloudFormFor(item);

    const normalizedName =
      String(
        getAppName(item)
      )
        .toLowerCase()
        .replace(
          /[^a-z0-9-]/g,
          "-"
        );

    setCloudForm(
      (current) => ({
        ...current,

        ecsService:
          current.ecsService ||
          `${normalizedName}-service`,

        taskFamily:
          current.taskFamily ||
          `${normalizedName}-task`,

        containerName:
          current.containerName ||
          normalizedName,
      })
    );
  }

  /*
   * ============================================================
   * CONTAINER -> AWS ECS
   *
   * IMPORTANT:
   * Target VM connection is NOT required here.
   * ============================================================
   */

  async function migrateContainerToCloud() {
    if (!cloudFormFor) {
      return;
    }

    const item =
      cloudFormFor;

    const id =
      getContainerId(item);

    const key =
      `cloud:${id}`;

    setBusyKey(key);

    setCloudStatuses(
      (state) => ({
        ...state,
        [id]: "loading",
      })
    );

    setNotice(null);

    try {
      const { data } =
        await axiosDiscoveryTool.post(
          API.migrateToCloud,
          {
            runid: existingRunId,

            userName:
              localStorage.getItem(
                "userName"
              ),

            groupName:
              localStorage.getItem(
                "groupName"
              ),

            name:
              getAppName(item),

            img:
              getImage(item),

            container_id:
              id,

            host_port:
              getHostPort(item),

            container_port:
              getContainerPort(item),

            source:
              sourceCred,

            ecr_repository:
              cloudForm.ecrRepository,

            aws_region:
              cloudForm.awsRegion,

            image_tag:
              cloudForm.imageTag,

            ecs_service:
              cloudForm.ecsService,

            task_family:
              cloudForm.taskFamily,

            container_name:
              cloudForm.containerName,

            task_cpu:
              cloudForm.taskCpu,

            task_memory:
              cloudForm.taskMemory,

            subnets:
              cloudForm.subnet
                .split(",")
                .map(
                  (value) =>
                    value.trim()
                )
                .filter(Boolean),

            security_groups:
              cloudForm.securityGroup
                .split(",")
                .map(
                  (value) =>
                    value.trim()
                )
                .filter(Boolean),

            desired_count: 1,

            assign_public_ip:
              "DISABLED",
          }
        );

      setCloudStatuses(
        (state) => ({
          ...state,
          [id]:
            data?.success === false
              ? "failed"
              : "success",
        })
      );

      setNotice({
        type:
          data?.success === false
            ? "error"
            : "success",

        text:
          data?.message ||
          (data?.success === false
            ? "Cloud migration failed."
            : `Container "${getAppName(
                item
              )}" migration to cloud completed.`),
      });

      setCloudFormFor(null);
    } catch (error) {
      setCloudStatuses(
        (state) => ({
          ...state,
          [id]: "failed",
        })
      );

      setNotice({
        type: "error",
        text:
          error?.response?.data?.message ||
          error?.message ||
          "Cloud migration failed.",
      });
    } finally {
      setBusyKey("");
    }
  }

  /*
   * ============================================================
   * NON-CONTAINER -> CONTAINER
   * ============================================================
   */

  async function makeContainer(
    item
  ) {
    const pid = item?.pid;

    const key =
      `containerize:${
        pid ?? getAppName(item)
      }`;

    setBusyKey(key);
    setNotice(null);

    try {
      const { data } =
        await axiosDiscoveryTool.post(
          API.containerizeNonContainer,
          {
            pid,

            tech_stack:
              item?.tech_stack ||
              item?.tech ||
              item?.technology ||
              "",

            source:
              sourceCred,

            target:
              targetVm,
          }
        );

      /*
       * Successful container response
       */

      if (
        data?.container_name ||
        data?.container_id ||
        data?.container
      ) {
        const created =
          data.container ||
          {
            name:
              data.container_name ||
              getAppName(item),

            container_id:
              data.container_id,

            img:
              data.img ||
              data.image,

            port:
              data.port,

            host_port:
              data.host_port ||
              data.port,

            container_port:
              data.container_port ||
              data.port,
          };

        setContainerizedPcf(
          (state) => ({
            ...state,
            [pid]: created,
          })
        );

        setNotice({
          type: "success",
          text:
            `Container created for "${getAppName(
              item
            )}".`,
        });

        await fetchTargetApplications();
      } else if (
        data?.containerfile
      ) {
        setNotice({
          type: "error",
          text:
            "Containerization needs a Containerfile edit/retry. This screen currently expects a successful container response.",
        });
      } else {
        setNotice({
          type: "error",
          text:
            data?.message ||
            data?.error ||
            "The API did not return a created container.",
        });
      }
    } catch (error) {
      setNotice({
        type: "error",
        text:
          error?.response?.data?.message ||
          error?.message ||
          "Containerization failed.",
      });
    } finally {
      setBusyKey("");
    }
  }

  /*
   * ============================================================
   * RENDER SOURCE ITEM
   * ============================================================
   */

  function renderSourceItem(
    item,
    category
  ) {
    const name =
      getAppName(item);

    const id =
      item?.pid ??
      getContainerId(item);

    const key =
      `${category}:${id}`;

    const pcf =
      category ===
        "nonContainer" &&
      isPcfApp(item);

    const generatedContainer =
      category ===
        "nonContainer"
        ? containerizedPcf[
            item?.pid
          ]
        : null;

    const busy =
      busyKey === key ||
      busyKey ===
        `pcf:${id}`;

    return (
      <div
        key={key}
        style={{
          border:
            "1px solid #e7ebf1",
          borderRadius: 9,
          padding: 12,
          marginBottom: 9,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems:
              "flex-start",
            justifyContent:
              "space-between",
            gap: 8,
          }}
        >
          <div
            style={{
              minWidth: 0,
            }}
          >
            <div
              style={{
                fontWeight: 700,
                color:
                  "#202b3c",
                overflowWrap:
                  "anywhere",
              }}
            >
              {name}
            </div>

            <div
              style={{
                fontSize: 12,
                color:
                  "#778195",
                marginTop: 4,
              }}
            >
              {category ===
              "container"
                ? `Image: ${
                    getImage(
                      item
                    ) ||
                    "Not provided"
                  }`
                : `PID: ${
                    item?.pid ??
                    "—"
                  }${
                    item?.tech_stack ||
                    item?.tech
                      ? ` · ${
                          item.tech_stack ||
                          item.tech
                        }`
                      : ""
                  }`}
            </div>

            {pcf && (
              <div
                style={{
                  marginTop: 7,
                  display:
                    "inline-flex",
                  gap: 5,
                  alignItems:
                    "center",
                  fontSize: 11,
                  borderRadius:
                    20,
                  padding:
                    "3px 8px",
                  background:
                    "#f3e8ff",
                  color:
                    "#6b21a8",
                }}
              >
                <Code2
                  size={13}
                />

                PCF application
              </div>
            )}
          </div>

          <span
            style={{
              color:
                "#7b8798",
              flexShrink: 0,
            }}
          >
            {category ===
            "container" ? (
              <Container
                size={18}
              />
            ) : (
              <Server
                size={18}
              />
            )}
          </span>
        </div>

        <div
          style={{
            display: "flex",
            flexWrap:
              "wrap",
            gap: 7,
            marginTop: 12,
          }}
        >
          {category ===
          "container" ? (
            <>
              {/* Container -> VM */}

              <button
                style={
                  primaryButton
                }
                disabled={
                  !targetConnected ||
                  !!busyKey
                }
                onClick={() =>
                  migrateContainerToVm(
                    item
                  )
                }
              >
                {busyKey ===
                key
                  ? "Migrating…"
                  : "Migrate to target"}
              </button>

              {/* Container -> Cloud */}

              <button
                style={
                  secondaryButton
                }
                disabled={
                  !!busyKey
                }
                onClick={() =>
                  startCloudMigration(
                    item
                  )
                }
              >
                {cloudStatuses[
                  getContainerId(
                    item
                  )
                  ] ===
                "success"
                  ? "Migrate again to cloud"
                  : "Migrate to cloud"}
              </button>
            </>
          ) : pcf ? (
            <>
              {!generatedContainer ? (
                /*
                 * PCF containerization
                 *
                 * Disabled until target is
                 * connected as requested.
                 */
                <button
                  style={
                    primaryButton
                  }
                  disabled={
                    !targetConnected ||
                    !!busyKey
                  }
                  onClick={() =>
                    makePcfApplicationContainer(
                      item
                    )
                  }
                >
                  {busy
                    ? "Preparing…"
                    : "Make it a container"}
                </button>
              ) : (
                <button
                  style={
                    primaryButton
                  }
                  disabled={
                    !targetConnected ||
                    !!busyKey
                  }
                  onClick={() =>
                    migratePcfContainer(
                      item
                    )
                  }
                >
                  Migrate created container
                </button>
              )}
            </>
          ) : (
            <>
              {/* Normal non-container migration */}

              <button
                style={
                  primaryButton
                }
                disabled={
                  !targetConnected ||
                  !!busyKey
                }
                onClick={() =>
                  migrateNonContainer(
                    item
                  )
                }
              >
                {busyKey ===
                key
                  ? "Migrating…"
                  : "Migrate to target"}
              </button>

              {/* Non-container -> Container */}

              <button
                style={
                  secondaryButton
                }
                disabled={
                  !targetConnected ||
                  !!busyKey
                }
                onClick={() =>
                  makeContainer(
                    item
                  )
                }
              >
                {busyKey ===
                `containerize:${id}`
                  ? "Containerizing…"
                  : "Migrate to container"}
              </button>
            </>
          )}
        </div>

        {generatedContainer && (
          <div
            style={{
              marginTop: 10,
              padding: 10,
              background:
                "#f0fdf4",
              borderRadius: 7,
              fontSize: 12,
            }}
          >
            <strong>
              Created container:
            </strong>{" "}
            {getAppName(
              generatedContainer
            )}
          </div>
        )}
      </div>
    );
  }

  /*
   * ============================================================
   * RENDER TARGET ITEM
   * ============================================================
   */

  function renderTargetItem(
    item,
    category
  ) {
    const name =
      getAppName(item);

    return (
      <div
        key={`${category}:${
          item?.pid ??
          getContainerId(item)
        }`}
        style={{
          border:
            "1px solid #e7ebf1",
          borderRadius: 9,
          padding: 12,
          marginBottom: 9,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems:
              "center",
            gap: 9,
          }}
        >
          {category ===
          "container" ? (
            <Container
              size={18}
              color="#3b82f6"
            />
          ) : (
            <Server
              size={18}
              color="#3b82f6"
            />
          )}

          <div
            style={{
              minWidth: 0,
            }}
          >
            <div
              style={{
                fontWeight: 700,
                overflowWrap:
                  "anywhere",
              }}
            >
              {name}
            </div>

            <div
              style={{
                fontSize: 12,
                color:
                  "#778195",
                marginTop: 4,
              }}
            >
              {category ===
              "container"
                ? `Image: ${
                    getImage(
                      item
                    ) ||
                    "Not provided"
                  }`
                : `PID: ${
                    item?.pid ??
                    "—"
                  }`}
            </div>
          </div>

          <span
            style={{
              marginLeft:
                "auto",
              color:
                "#15803d",
            }}
            title="Found on target"
          >
            <CheckCircle2
              size={17}
            />
          </span>
        </div>
      </div>
    );
  }

  /*
   * ============================================================
   * RUN STEP
   * ============================================================
   */

  if (
    showRunStep &&
    applicationStatus
  ) {
    return (
      <RunStep
        setStep={setStep}
        target={targetVm}
        source={sourceCred}
        applicationStatus={
          applicationStatus
        }
        summary={summary}
        setRunStep={
          setRunStep
        }
      />
    );
  }

  /*
   * ============================================================
   * CATEGORIES
   * ============================================================
   */

  const categories = [
    {
      id: "container",
      label:
        "Container Migration",
      icon: Container,
    },

    {
      id: "nonContainer",
      label:
        "Non-container Migration",
      icon: Server,
    },

    {
      id:
        "nonContainerToContainer",
      label:
        "Non-container to container",
      icon: Boxes,
    },

    {
      id: "pcf",
      label:
        "PCF Application Migration",
      icon: Code2,
    },
  ];

  /*
   * ============================================================
   * SOURCE CATEGORY DATA
   * ============================================================
   */

  const categorySourceItems =
    activeCategory ===
    "container"
      ? sourceContainers
      : activeCategory ===
        "pcf"
      ? sourceNonContainers.filter(
          isPcfApp
        )
      : sourceNonContainers;

  /*
   * ============================================================
   * TARGET CATEGORY
   *
   * Container:
   * - Container Migration
   * - Non-container -> Container
   * - PCF
   *
   * Non-container:
   * - Normal Non-container Migration
   * ============================================================
   */

  const categoryTargetType =
    activeCategory ===
    "nonContainer"
      ? "nonContainer"
      : "container";

  const categoryTargetItems =
    categoryTargetType ===
    "container"
      ? targetContainers
      : targetNonContainers;

  const categorySourceLoading =
    activeCategory ===
    "container"
      ? sourceLoading.container
      : sourceLoading.nonContainer;

  const categoryTargetLoading =
    targetLoading[
      categoryTargetType
    ];

  const categorySourceError =
    activeCategory ===
    "container"
      ? sourceErrors.container
      : sourceErrors.nonContainer;

  const categoryTargetError =
    targetErrors[
      categoryTargetType
    ];

  /*
   * ============================================================
   * UI
   * ============================================================
   */

  return (
    <div
      style={{
        padding:
          "4px 0 20px",
        color:
          "#202b3c",
      }}
    >
      {/* ======================================================
          HEADER
          ====================================================== */}

      <div
        style={{
          display: "flex",
          alignItems:
            "center",
          gap: 10,
          marginBottom: 16,
        }}
      >
        <ArrowRight
          size={24}
          color="#e87524"
        />

        <div>
          <h2
            style={{
              margin: 0,
              fontSize: 23,
            }}
          >
            Transfer
          </h2>

          <div
            style={{
              color:
                "#778195",
              fontSize: 13,
              marginTop: 3,
            }}
          >
            Choose a migration type,
            review source
            applications, and
            select a target action.
          </div>
        </div>
      </div>

      {/* ======================================================
          MIGRATION CATEGORY SELECTOR
          ====================================================== */}

      <div
        style={{
          display:
            "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(190px, 1fr))",
          gap: 9,
          marginBottom: 16,
        }}
      >
        {categories.map(
          ({
            id,
            label,
            icon: Icon,
          }) => (
            <button
              key={id}
              onClick={() =>
                setActiveCategory(
                  id
                )
              }
              style={{
                ...buttonStyle,

                textAlign:
                  "left",

                border:
                  activeCategory ===
                  id
                    ? "1px solid #e87524"
                    : "1px solid #dce2ea",

                background:
                  activeCategory ===
                  id
                    ? "#fff5ed"
                    : "#fff",

                color:
                  activeCategory ===
                  id
                    ? "#a84b0b"
                    : "#344054",

                padding:
                  "12px 13px",

                display:
                  "flex",

                alignItems:
                  "center",

                gap: 9,
              }}
            >
              <Icon
                size={18}
              />

              <span>
                {label}
              </span>
            </button>
          )
        )}
      </div>

      {/* ======================================================
          SOURCE + TARGET TWO PANEL LAYOUT
          ====================================================== */}

      <div
        style={{
          display:
            "grid",

          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(100%, 390px), 1fr))",

          gap: 14,

          alignItems:
            "start",
        }}
      >
        {/* ====================================================
            LEFT PANEL - SOURCE
            ==================================================== */}

        <section
          style={
            panelStyle
          }
        >
          <div
            style={
              panelHeaderStyle
            }
          >
            <div
              style={{
                display:
                  "flex",
                alignItems:
                  "center",
                gap: 8,
              }}
            >
              <Server
                size={19}
                color="#e87524"
              />

              <div>
                <div
                  style={{
                    fontWeight:
                      750,
                  }}
                >
                  Source
                </div>

                <div
                  style={{
                    fontSize:
                      12,
                    color:
                      "#778195",
                  }}
                >
                  {sourceCred?.host ||
                    sourceCred?.ip ||
                    "Source VM"}
                </div>
              </div>
            </div>

            <button
              title="Refresh source data"
              style={{
                ...secondaryButton,
                padding: 7,
              }}
              onClick={() => {
                fetchSourceContainers();
                fetchSourceNonContainers();
              }}
            >
              <RefreshCw
                size={15}
              />
            </button>
          </div>

          <div
            style={{
              padding: 14,
            }}
          >
            <div
              style={{
                fontSize: 12,
                color:
                  "#687386",
                marginBottom:
                  10,
              }}
            >
              {activeCategory ===
              "container"
                ? "Containers discovered on the source"
                : activeCategory ===
                  "nonContainer"
                ? "Non-container applications discovered on the source"
                : activeCategory ===
                  "nonContainerToContainer"
                ? "Select a source application to containerize"
                : "Applications identified as PCF by the API response"}
            </div>

            {/*
             * Source loading spinner
             */}

            {categorySourceLoading ? (
              <Spinner
                label="Fetching source applications…"
              />
            ) : categorySourceError ? (
              <div
                style={{
                  color:
                    "#b42318",
                  fontSize:
                    13,
                }}
              >
                <AlertCircle
                  size={15}
                  style={{
                    verticalAlign:
                      "middle",
                    marginRight: 5,
                  }}
                />

                {categorySourceError}

                <div>
                  <button
                    style={{
                      ...secondaryButton,
                      marginTop: 9,
                    }}
                    onClick={() =>
                      activeCategory ===
                      "container"
                        ? fetchSourceContainers()
                        : fetchSourceNonContainers()
                    }
                  >
                    Retry
                  </button>
                </div>
              </div>
            ) : categorySourceItems.length ? (
              categorySourceItems.map(
                (item) => {
                  /*
                   * Container migration
                   */

                  if (
                    activeCategory ===
                    "container"
                  ) {
                    return renderSourceItem(
                      item,
                      "container"
                    );
                  }

                  /*
                   * PCF migration
                   */

                  if (
                    activeCategory ===
                    "pcf"
                  ) {
                    return renderSourceItem(
                      item,
                      "nonContainer"
                    );
                  }

                  /*
                   * Non-container -> container
                   */

                  if (
                    activeCategory ===
                    "nonContainerToContainer"
                  ) {
                    return (
                      <div
                        key={`convert:${item?.pid}`}
                        style={{
                          border:
                            "1px solid #e7ebf1",
                          borderRadius:
                            9,
                          padding: 12,
                          marginBottom:
                            9,
                        }}
                      >
                        <div
                          style={{
                            fontWeight:
                              700,
                          }}
                        >
                          {getAppName(
                            item
                          )}
                        </div>

                        <div
                          style={{
                            fontSize:
                              12,
                            color:
                              "#778195",
                            margin:
                              "4px 0 11px",
                          }}
                        >
                          PID:{" "}
                          {item?.pid ??
                            "—"}{" "}
                          ·{" "}
                          {item?.tech_stack ||
                            item?.tech ||
                            "Technology not provided"}
                        </div>

                        <button
                          style={
                            primaryButton
                          }
                          disabled={
                            !targetConnected ||
                            !!busyKey
                          }
                          onClick={() =>
                            makeContainer(
                              item
                            )
                          }
                        >
                          {busyKey ===
                          `containerize:${
                            item?.pid ??
                            getAppName(
                              item
                            )
                          }`
                            ? "Containerizing…"
                            : "Create container"}
                        </button>
                      </div>
                    );
                  }

                  /*
                   * Normal non-container
                   */

                  return renderSourceItem(
                    item,
                    "nonContainer"
                  );
                }
              )
            ) : (
              <EmptyState>
                {activeCategory ===
                "pcf"
                  ? "No PCF application was found in the source API response. The PCF keyword is detected from application metadata."
                  : "No applications found for this category."}
              </EmptyState>
            )}
          </div>
        </section>

        {/* ====================================================
            RIGHT PANEL - TARGET
            ==================================================== */}

        <section
          style={
            panelStyle
          }
        >
          <div
            style={
              panelHeaderStyle
            }
          >
            <div
              style={{
                display:
                  "flex",
                alignItems:
                  "center",
                gap: 8,
              }}
            >
              {activeCategory ===
              "container" ? (
                <Cloud
                  size={19}
                  color="#3b82f6"
                />
              ) : (
                <Server
                  size={19}
                  color="#3b82f6"
                />
              )}

              <div>
                <div
                  style={{
                    fontWeight:
                      750,
                  }}
                >
                  Target
                </div>

                <div
                  style={{
                    fontSize:
                      12,
                    color:
                      targetConnected
                        ? "#15803d"
                        : "#778195",
                  }}
                >
                  {targetConnected
                    ? `Connected · ${targetVm.ip}`
                    : "Connect to a target VM"}
                </div>
              </div>
            </div>

            {targetConnected && (
              <span
                style={{
                  fontSize: 11,
                  color:
                    "#15803d",
                  display:
                    "inline-flex",
                  alignItems:
                    "center",
                  gap: 4,
                }}
              >
                <CheckCircle2
                  size={14}
                />

                Connected
              </span>
            )}
          </div>

          <div
            style={{
              padding: 14,
            }}
          >
            {/* ==================================================
                TARGET CONNECTION FORM
                ================================================== */}

            <div
              style={{
                display:
                  "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(145px, 1fr))",
                gap: 9,
              }}
            >
              <label
                style={{
                  fontSize:
                    12,
                  color:
                    "#596579",
                }}
              >
                VM IP

                <input
                  style={{
                    ...fieldStyle,
                    marginTop: 5,
                  }}
                  name="ip"
                  value={
                    targetVm.ip
                  }
                  onChange={(
                    e
                  ) =>
                    setTargetVm(
                      (state) => ({
                        ...state,
                        ip:
                          e.target
                            .value,
                      })
                    )
                  }
                  placeholder="Target IP"
                />
              </label>

              <label
                style={{
                  fontSize:
                    12,
                  color:
                    "#596579",
                }}
              >
                Username

                <input
                  style={{
                    ...fieldStyle,
                    marginTop: 5,
                  }}
                  name="TargetUsername"
                  value={
                    targetVm.TargetUsername
                  }
                  onChange={(
                    e
                  ) =>
                    setTargetVm(
                      (state) => ({
                        ...state,
                        TargetUsername:
                          e.target
                            .value,
                      })
                    )
                  }
                  placeholder="Username"
                />
              </label>

              <label
                style={{
                  fontSize:
                    12,
                  color:
                    "#596579",
                }}
              >
                Password

                <input
                  style={{
                    ...fieldStyle,
                    marginTop: 5,
                  }}
                  type="password"
                  name="TargetPassword"
                  value={
                    targetVm.TargetPassword
                  }
                  onChange={(
                    e
                  ) =>
                    setTargetVm(
                      (state) => ({
                        ...state,
                        TargetPassword:
                          e.target
                            .value,
                      })
                    )
                  }
                  placeholder="Password"
                />
              </label>

              <label
                style={{
                  fontSize:
                    12,
                  color:
                    "#596579",
                }}
              >
                Sudo password

                <input
                  style={{
                    ...fieldStyle,
                    marginTop: 5,
                  }}
                  type="password"
                  name="TargetSudoPassword"
                  value={
                    targetVm.TargetSudoPassword
                  }
                  onChange={(
                    e
                  ) =>
                    setTargetVm(
                      (state) => ({
                        ...state,
                        TargetSudoPassword:
                          e.target
                            .value,
                      })
                    )
                  }
                  placeholder="Sudo password"
                />
              </label>
            </div>

            <div
              style={{
                display:
                  "flex",
                alignItems:
                  "center",
                gap: 10,
                marginTop: 11,
                flexWrap:
                  "wrap",
              }}
            >
              <button
                style={
                  primaryButton
                }
                disabled={
                  targetStatus ===
                    "connecting" ||
                  !targetVm.ip ||
                  !targetVm.TargetUsername ||
                  !targetVm.TargetPassword
                }
                onClick={
                  connectTarget
                }
              >
                {targetStatus ===
                "connecting"
                  ? "Connecting…"
                  : targetConnected
                  ? "Reconnect target"
                  : "Connect target"}
              </button>

              {targetStatus ===
                "connecting" && (
                <Spinner
                  label="Connecting to target…"
                />
              )}
            </div>

            {targetError && (
              <div
                style={{
                  color:
                    "#b42318",
                  fontSize:
                    12,
                  marginTop: 8,
                }}
              >
                {targetError}
              </div>
            )}

            {/* ==================================================
                TARGET APPLICATIONS
                ================================================== */}

            <div
              style={{
                borderTop:
                  "1px solid #e8edf3",
                marginTop: 15,
                paddingTop: 13,
              }}
            >
              <div
                style={{
                  fontWeight:
                    700,
                  marginBottom:
                    4,
                }}
              >
                {categoryTargetType ===
                "container"
                  ? "Target containers"
                  : "Target non-container applications"}
              </div>

              <div
                style={{
                  color:
                    "#778195",
                  fontSize:
                    12,
                  marginBottom:
                    8,
                }}
              >
                {activeCategory ===
                "container"
                  ? "Cloud migration can be started without connecting this target VM."
                  : activeCategory ===
                    "nonContainerToContainer"
                  ? "Created containers will appear here after a successful target refresh."
                  : activeCategory ===
                    "pcf"
                  ? "The created PCF container will be migrated here after containerization is implemented."
                  : "Target applications are loaded after a successful target connection."}
              </div>

              {/*
               * Container migration does not require
               * target connection for cloud migration.
               */

              {activeCategory ===
                "container" &&
              !targetConnected ? (
                <EmptyState>
                  Connect a target to
                  list target
                  containers. The
                  “Migrate to cloud”
                  action on the source
                  remains available.
                </EmptyState>
              ) : !targetConnected ? (
                <EmptyState>
                  Connect to the target
                  to enable migration
                  and load its
                  applications.
                </EmptyState>
              ) : categoryTargetLoading ? (
                <Spinner
                  label="Fetching target applications…"
                />
              ) : categoryTargetError ? (
                <div
                  style={{
                    color:
                      "#b42318",
                    fontSize:
                      13,
                  }}
                >
                  {categoryTargetError}

                  <div>
                    <button
                      style={{
                        ...secondaryButton,
                        marginTop: 8,
                      }}
                      onClick={
                        fetchTargetApplications
                      }
                    >
                      Retry
                    </button>
                  </div>
                </div>
              ) : categoryTargetItems.length ? (
                categoryTargetItems.map(
                  (item) =>
                    renderTargetItem(
                      item,
                      categoryTargetType
                    )
                )
              ) : (
                <EmptyState>
                  No target{" "}
                  {categoryTargetType ===
                  "container"
                    ? "containers"
                    : "non-container applications"}{" "}
                  found.
                </EmptyState>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* ========================================================
          NOTICE
          ======================================================== */}

      {notice && (
        <div
          role="status"
          style={{
            display:
              "flex",
            alignItems:
              "flex-start",
            gap: 8,
            marginTop: 14,
            padding: 12,
            borderRadius: 8,

            border:
              `1px solid ${
                notice.type ===
                "error"
                  ? "#f3b6b6"
                  : notice.type ===
                    "success"
                  ? "#b7e4c7"
                  : "#cbd5e1"
              }`,

            background:
              notice.type ===
              "error"
                ? "#fff5f5"
                : notice.type ===
                  "success"
                ? "#f0fdf4"
                : "#f8fafc",

            color:
              notice.type ===
              "error"
                ? "#b42318"
                : notice.type ===
                  "success"
                ? "#166534"
                : "#344054",

            fontSize: 13,
          }}
        >
          {notice.type ===
          "error" ? (
            <AlertCircle
              size={17}
            />
          ) : (
            <CheckCircle2
              size={17}
            />
          )}

          <span>
            {notice.text}
          </span>

          <button
            style={{
              ...secondaryButton,
              marginLeft:
                "auto",
              padding:
                "3px 8px",
            }}
            onClick={() =>
              setNotice(null)
            }
          >
            Dismiss
          </button>
        </div>
      )}

      {/* ========================================================
          CLOUD MIGRATION MODAL
          ======================================================== */}

      {cloudFormFor && (
        <div
          style={{
            position:
              "fixed",
            inset: 0,
            zIndex: 1000,
            background:
              "rgba(15,23,42,.45)",
            display:
              "flex",
            alignItems:
              "center",
            justifyContent:
              "center",
            padding: 16,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Cloud migration configuration"
            style={{
              background:
                "#fff",
              borderRadius:
                12,
              width:
                "min(680px, 100%)",
              maxHeight:
                "90vh",
              overflow:
                "auto",
              boxShadow:
                "0 20px 60px rgba(0,0,0,.2)",
            }}
          >
            <div
              style={
                panelHeaderStyle
              }
            >
              <div>
                <div
                  style={{
                    fontWeight:
                      750,
                    fontSize:
                      17,
                  }}
                >
                  Migrate container
                  to AWS ECS
                </div>

                <div
                  style={{
                    color:
                      "#778195",
                    fontSize:
                      12,
                    marginTop: 3,
                  }}
                >
                  Source:{" "}
                  {getAppName(
                    cloudFormFor
                  )}{" "}
                  · Target VM
                  connection is not
                  required.
                </div>
              </div>

              <button
                style={
                  secondaryButton
                }
                onClick={() =>
                  setCloudFormFor(
                    null
                  )
                }
              >
                Close
              </button>
            </div>

            <div
              style={{
                padding: 16,
                display:
                  "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(210px, 1fr))",
                gap: 12,
              }}
            >
              {[
                [
                  "ecrRepository",
                  "ECR repository",
                ],
                [
                  "awsRegion",
                  "AWS region",
                ],
                [
                  "imageTag",
                  "Image tag",
                ],
                [
                  "ecsService",
                  "ECS service",
                ],
                [
                  "taskFamily",
                  "Task family",
                ],
                [
                  "containerName",
                  "Container name",
                ],
                [
                  "taskCpu",
                  "Task CPU",
                ],
                [
                  "taskMemory",
                  "Task memory (MiB)",
                ],
                [
                  "subnet",
                  "Subnet IDs (comma-separated)",
                ],
                [
                  "securityGroup",
                  "Security group IDs (comma-separated)",
                ],
              ].map(
                ([
                  name,
                  label,
                ]) => (
                  <label
                    key={name}
                    style={{
                      fontSize:
                        12,
                      color:
                        "#596579",
                    }}
                  >
                    {label}

                    <input
                      style={{
                        ...fieldStyle,
                        marginTop: 5,
                      }}
                      value={
                        cloudForm[
                          name
                        ]
                      }
                      onChange={(
                        e
                      ) =>
                        setCloudForm(
                          (state) => ({
                            ...state,
                            [name]:
                              e.target
                                .value,
                          })
                        )
                      }
                      placeholder={
                        label
                      }
                    />
                  </label>
                )
              )}
            </div>

            <div
              style={{
                padding:
                  "0 16px 16px",
                display:
                  "flex",
                justifyContent:
                  "flex-end",
                gap: 8,
              }}
            >
              <button
                style={
                  secondaryButton
                }
                onClick={() =>
                  setCloudFormFor(
                    null
                  )
                }
              >
                Cancel
              </button>

              <button
                style={
                  primaryButton
                }
                disabled={
                  !!busyKey ||
                  !cloudForm.ecrRepository ||
                  !cloudForm.awsRegion ||
                  !cloudForm.imageTag ||
                  !cloudForm.ecsService ||
                  !cloudForm.taskFamily ||
                  !cloudForm.containerName
                }
                onClick={
                  migrateContainerToCloud
                }
              >
                {busyKey.startsWith(
                  "cloud:"
                )
                  ? "Migrating to cloud…"
                  : "Start cloud migration"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
