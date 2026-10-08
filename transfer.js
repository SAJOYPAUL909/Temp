"use client";

import {
    Check,
    CheckCircle,
    SendToBack,
    X,
    FileText,
    Play,
    Loader2,
} from "lucide-react";
import RunStep from "./RunStep";
import { useEffect, useState } from "react";
import useSourceCredentialStore from "../../store/sourceCredentialStore";
import useRunStore from "../../store/runStore";
import styles from "../../styles/Popup.module.css";
import stylesT from "../../styles/Transfer.module.css";
import config from "../../config/config";

export default function TransferStep({
    setStep,
    source,
    test_connection,
    summary,
    setRunStep
}) {
    const [isConnected, setIsConnected] = useState(false);
    const [showResult, setShowResult] = useState(false);
    const [prereqLoading, setPrereqLoading] = useState(false);
    const [prereqData, setPrereqData] = useState([]);
    const [showPrereq, setShowPrereq] = useState(false);

    const groupByPid = (Array.isArray(prereqData) ? prereqData : [])
        .filter(
            item =>
                item.pid !== null &&
                item.pid !== undefined
        )
        .reduce((acc, item) => {
            if (!acc[item.pid]) {
                acc[item.pid] = [];
            }

            acc[item.pid].push(item);
            return acc;
        }, {});

    const pidGroups = Object.entries(groupByPid);

    const Row = ({ item }) => {
        const isAvailable = item.status === "available";

        return (
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    marginBottom: "8px",
                }}
            >
                <div
                    style={{
                        width: "16px",
                        height: "16px",
                        borderRadius: "50%",
                        marginRight: "10px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        backgroundColor: isAvailable
                            ? "#28a745"
                            : "#ccc",
                        color: "#fff",
                        fontSize: "10px",
                        fontWeight: "bold",
                    }}
                >
                    {isAvailable ? <Check /> : ""}
                </div>

                <span>{item.name}</span>
            </div>
        );
    };

    const [isTransferring, setIsTransferring] = useState(false);
    const [isDone, setIsDone] = useState(false);
    const [transferringName, setTransferringName] = useState("");
    const [transferPort, setTransferPort] = useState("");
    const [isRun, setIsRun] = useState(false);
    const [IsRunApplication, setIsRunApplication] = useState(false);

    const [sourceNonContainers, setSourceNonContainers] =
        useState(null);

    const [targetNonContainers, setTargetNonContainers] =
        useState(null);

    const [nonContainerRunCommand, setNonContainerRunCommand] =
        useState("");

    const [nonContainerFinalResult, setnonContainerFinalResult] =
        useState("");

    const [loadingNonContainerId, setLoadingNonContainerId] =
        useState(null);

    const [recommendation, setRecommendation] =
        useState("");

    const [
        isStatusContainerizedApplication,
        setIsStatusContainerizedApplication
    ] = useState(false);

    const [status, setStatus] = useState(false);
    const [isLift, setIsLift] = useState(false);
    const [lifting, setLifting] = useState(false);

    const [containers, setContainers] =
        useState(null);

    const [target_containers, setTarget_containers] =
        useState(null);

    const [isTarget, setIsTarget] =
        useState(false);

    const [isMigrating, setIsMigrating] =
        useState(false);

    const [loadingId, setLoadingId] =
        useState(null);

    const [pathLocation, setPathLocation] =
        useState("");

    const [applicationStatus, setApplicationStatus] =
        useState(null);

    const [containerRunCommand, setContainerRunCommand] =
        useState("");

    const [isRunContainer, setIsRunContainer] =
        useState(false);

    const [isOpen, setIsOpen] =
        useState(false);

    const [sshStatus, setSshStatus] =
        useState(null);

    const [sshError, setSshError] =
        useState(null);

    const {
        sourceCredential,
        setSourceCredential
    } = useSourceCredentialStore();

    const {
        existingRunId,
        setExistingRunId
    } = useRunStore();

    const [loading, setLoading] =
        useState(false);

    /*
     * ============================================================
     * NON-CONTAINER OPERATION LOCK
     * ============================================================
     *
     * null
     * transfer
     * containerize
     * edited-containerize
     *
     * Transfer and containerization are therefore mutually
     * exclusive.
     */
    const [
        activeNonContainerOperation,
        setActiveNonContainerOperation
    ] = useState(null);

    /*
     * ============================================================
     * CONTAINERFILE EDITOR
     * ============================================================
     *
     * This is populated when the backend completes its automatic
     * 5-attempt repair loop and returns the latest Containerfile.
     */
    const [
        containerfileEditor,
        setContainerfileEditor
    ] = useState({
        open: false,
        pid: null,
        port: "",
        fileName: "Containerfile",
        content: "",
        attempts: 0,
        runtime: "",
        applicationTransferred: false,
        failureDetails: null,
    });

    const [
        editedContainerfileRunning,
        setEditedContainerfileRunning
    ] = useState(false);

    console.log(
        "source credential in lift and shift: ",
        sourceCredential
    );

    const [isTargetConnect, setIsTargetConnect] =
        useState(false);

    const [targetVm, setTargetVm] = useState({
        ip: "",
        TargetUsername: "",
        TargetPassword: "",
        TargetSudoPassword: "",
    });

    const handleBack = () => {
        if (onBack) {
            onBack();
        }
    };

    useEffect(() => {
        const stored =
            localStorage.getItem("targetVm");

        if (stored) {
            setTargetVm(
                JSON.parse(stored)
            );
        }

        const prereqData =
            localStorage.getItem("pre-req");

        if (prereqData) {
            setPrereqData(
                JSON.parse(prereqData)
            );
        }
    }, []);

    const handleChange = e => {
        setTargetVm({
            ...targetVm,
            [e.target.name]:
                e.target.value,
        });
    };

    console.log(
        "this local storage data: ",
        targetVm
    );

    async function testSshConnection() {
        localStorage.setItem(
            "targetVm",
            JSON.stringify(targetVm)
        );

        setSshStatus("connecting");
        setSshError(null);

        try {
            const res = await fetch(
                `${config.BASE_PATH}/api/test_ssh`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify({
                        host: targetVm.ip,
                        user:
                            targetVm.TargetUsername,
                        password:
                            targetVm.TargetPassword,
                        sudo_password:
                            targetVm.TargetSudoPassword,
                    }),
                }
            );

            const j = await res.json();

            if (!res.ok) {
                setSshStatus("error");
                setSshError(
                    j.message ||
                    "SSH failed"
                );

                return false;
            }

            setSshStatus("connected");
            setIsTargetConnect(true);
            setIsConnected(true);

            runPrereqCheck();

            return true;
        } catch (e) {
            setSshStatus("error");
            setSshError(e.message);
            setIsConnected(false);

            return false;
        }
    }

    /*
     * ============================================================
     * PREREQUISITE CHECK
     * ============================================================
     */

    async function runPrereqCheck() {
        setPrereqLoading(true);

        const prereqData =
            localStorage.getItem("pre-req");

        if (prereqData) {
            setPrereqData(
                JSON.parse(prereqData)
            );
        }

        setShowResult(true);

        try {
            const res1 =
                await fetch(
                    `${config.BASE_PATH}/api/get-prereq-check/${existingRunId}`,
                    {
                        method: "GET",
                    }
                );

            const data =
                await res1.json();

            if (data.data == null) {
                const res =
                    await fetch(
                        `${config.BASE_PATH}/api/get-prereqs/${existingRunId}`,
                        {
                            method: "GET",
                        }
                    );

                if (!res.ok) {
                    const text =
                        await res.text();

                    console.error(
                        "API ERROR:",
                        text
                    );

                    throw new Error(
                        "API failed"
                    );
                }

                const data =
                    await res.json();

                setPrereqData(
                    data.data || []
                );
            } else {
                setPrereqData(
                    data.data
                );
            }
        } catch (err) {
            console.error(
                "ERROR:",
                err
            );

            alert(
                err.message ||
                "prerequisite check failed"
            );
        } finally {
            setPrereqLoading(false);
        }
    }

    /*
     * ============================================================
     * PREREQUISITE STREAMING CHECK
     * ============================================================
     */

    async function PrereqCheck() {
        setShowResult(true);

        try {
            setPrereqLoading(true);

            const res =
                await fetch(
                    `${config.BASE_PATH}/api/run-prereqs/${existingRunId}`,
                    {
                        method: "POST",
                        body: JSON.stringify({
                            host:
                                targetVm.ip,
                            password:
                                targetVm.TargetPassword,
                            sudo_password:
                                targetVm.TargetSudoPassword,
                            type: "ssh",
                            user:
                                targetVm.TargetUsername
                        }),
                        headers: {
                            "Content-Type":
                                "application/json",
                            Accept:
                                "text/event-stream",
                        },
                    }
                );

            if (!res.ok) {
                const text =
                    await res.text();

                console.error(
                    "API ERROR:",
                    text
                );

                throw new Error(
                    "API failed"
                );
            }

            const reader =
                res.body.getReader();

            const decoder =
                new TextDecoder(
                    "utf-8"
                );

            let buffer = "";

            while (true) {
                const {
                    value,
                    done
                } =
                    await reader.read();

                if (done) {
                    break;
                }

                buffer +=
                    decoder.decode(
                        value,
                        {
                            stream: true
                        }
                    );

                const parts =
                    buffer.split(
                        "\n\n"
                    );

                buffer =
                    parts.pop();

                for (
                    let part of parts
                ) {
                    if (
                        part.startsWith(
                            "data:"
                        )
                    ) {
                        const jsonStr =
                            part
                                .replace(
                                    "data:",
                                    ""
                                )
                                .trim();

                        if (
                            jsonStr ===
                            "[DONE]"
                        ) {
                            console.log(
                                "Stream finished"
                            );

                            continue;
                        }

                        try {
                            const parsed =
                                JSON.parse(
                                    jsonStr
                                );

                            setPrereqData(
                                prev => {
                                    const exists =
                                        prev?.find(
                                            item =>
                                                item.name ===
                                                parsed.name
                                        );

                                    if (exists) {
                                        return prev.map(
                                            item => {
                                                if (
                                                    item.name ===
                                                    parsed.name
                                                ) {
                                                    return {
                                                        ...item,
                                                        ...parsed
                                                    };
                                                }

                                                return item;
                                            }
                                        );
                                    } else {
                                        return prev
                                            ? [
                                                ...prev,
                                                parsed
                                            ]
                                            : [
                                                parsed
                                            ];
                                    }
                                }
                            );

                            localStorage.setItem(
                                "pre-req",
                                JSON.stringify(
                                    prereqData
                                )
                            );
                        } catch (err) {
                            console.error(
                                "JSON parse error:",
                                err,
                                jsonStr
                            );
                        }
                    }
                }
            }
        } catch (err) {
            console.error(
                "ERROR:",
                err
            );

            alert(
                err.message ||
                "prerequisite check failed"
            );
        } finally {
            setPrereqLoading(false);
        }
    }

    const [testConn, setTestConn] =
        useState(false);

    useEffect(() => {
        setTestConn(
            test_connection
        );
    }, [test_connection]);

    if (testConn) {
        testSshConnection();
        setTestConn(false);
    }

    /*
     * ============================================================
     * TARGET CONTAINERS
     * ============================================================
     */

    const get_target_containers =
        async () => {
            try {
                const res =
                    await fetch(
                        `${config.BASE_PATH}/api/get-target-containers`,
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json",
                            },
                            body: JSON.stringify({
                                target:
                                    targetVm,
                            }),
                        }
                    );

                const cont =
                    await res.json();

                if (
                    cont.containers
                ) {
                    setTarget_containers(
                        cont.containers
                    );
                }
            } catch (e) {
                console.log(
                    "failed to fetch containers:",
                    e
                );
            }
        };

    useEffect(() => {
        if (!isTargetConnect) {
            return;
        }

        get_target_containers();
    }, [isTargetConnect]);

    console.log(
        "this is container: ",
        containers
    );

    console.log(
        "this is target container: ",
        target_containers
    );

    /*
     * ============================================================
     * LIFT SHIFT
     * ============================================================
     */

    async function execute() {
        const payload = {
            source:
                sourceCredential,
            target:
                targetVm,
        };

        setLifting(true);

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/lift-shift`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            payload
                        }),
                    }
                );

            const j =
                await res.json();

            if (j) {
                setStatus(true);

                alert(
                    "Image Transfer succesfully !"
                );
            } else {
                setStatus(true);

                alert(
                    "Failed to do migration"
                );
            }

            setLifting(false);
        } catch (e) {
            setStatus(false);
            setLifting(false);

            alert(
                "Failed to do migration"
            );
        }
    }

    /*
     * ============================================================
     * EXISTING CONTAINER MIGRATION
     * ============================================================
     */

    async function handleMigrate(
        name,
        host_port,
        container_port,
        img
    ) {
        console.log(
            "this is name in handleMigrate"
        );

        setLoadingId(name);
        setTransferringName(name);

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/shift-single`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            name: name,
                            img: img,
                            host_port:
                                host_port,
                            container_port:
                                container_port,
                            source:
                                sourceCredential,
                            target:
                                targetVm,
                        }),
                    }
                );

            const j =
                await res.json();

            setIsTarget(true);

            setContainerRunCommand(
                j.container_run_command
            );

            console.log(
                "Response of migrated container : ",
                j
            );

            setIsStatusContainerizedApplication(
                true
            );

            console.log(
                "this is message from migrate",
                j
            );
        } catch (e) {
            console.log(
                "Failed to do migration of single"
            );
        } finally {
            setLoadingId(null);
            setIsTargetConnect(true);
        }
    }

    /*
     * ============================================================
     * RUN NON-CONTAINER APPLICATION
     * ============================================================
     */

    async function runNonContainer() {
        setIsRunContainer(true);

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/run-non-container`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            run_container_command:
                                nonContainerRunCommand,
                            container_final_result:
                                nonContainerFinalResult,
                            target:
                                targetVm,
                            port:
                                transferPort,
                        }),
                    }
                );

            const j =
                await res.json();

            console.log(
                "Container running ... : ",
                j
            );

            if (j) {
                setApplicationStatus(
                    j
                );

                setIsTargetConnect(
                    true
                );

                setIsOpen(false);

                setIsRunContainer(
                    false
                );

                setIsRunApplication(
                    true
                );
            }
        } catch (e) {
            console.log(
                "Failed to do migration of single"
            );
        } finally {
            setIsRunContainer(
                false
            );

            setIsRunApplication(
                true
            );
        }
    }

    /*
     * ============================================================
     * TARGET NON-CONTAINER APPLICATIONS
     * ============================================================
     */

    const getTargetNonContainers =
        async () => {
            try {
                const res =
                    await fetch(
                        `${config.BASE_PATH}/api/get-target-non-container`,
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json",
                            },
                            body: JSON.stringify({
                                target:
                                    targetVm,
                            }),
                        }
                    );

                const cont =
                    await res.json();

                if (
                    cont.target_non_containerized
                ) {
                    setTargetNonContainers(
                        cont.target_non_containerized
                    );
                }
            } catch (e) {
                console.log(
                    "failed to fetch non container applications of target vm:",
                    e
                );
            }
        };

    useEffect(() => {
        if (!isTargetConnect) {
            return;
        }

        getTargetNonContainers();
    }, [isTargetConnect]);

    /*
     * ============================================================
     * NORMAL NON-CONTAINER TRANSFER
     * ============================================================
     */

    async function handleNonContainerizedMigrate(
        pid,
        local
    ) {
        /*
         * Do not allow transfer while any containerization
         * operation is running.
         */
        if (activeNonContainerOperation) {
            return;
        }

        console.log(
            "this is name in handleNonContainerizedMigrate"
        );

        setActiveNonContainerOperation(
            "transfer"
        );

        setLoadingNonContainerId(
            pid
        );

        setIsOpen(true);
        setIsTransferring(true);
        setIsDone(false);

        setTransferringName(
            pid
        );

        setTransferPort(
            local
        );

        setSourceNonContainers(
            prev =>
                (
                    Array.isArray(prev)
                        ? prev
                        : []
                ).map(
                    app =>
                        app.pid === pid
                            ? {
                                ...app,
                                transferring: true,
                                migratingToContainer:
                                    false
                            }
                            : app
                )
        );

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/non-container-shift-single`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            pid:
                                pid,
                            source:
                                sourceCredential,
                            target:
                                targetVm,
                        }),
                    }
                );

            const j =
                await res.json();

            setnonContainerFinalResult(
                j.non_containerized_res
            );

            setNonContainerRunCommand(
                j.run_command_non_container
            );

            setPathLocation(
                j.path_location
            );

            setRecommendation(
                j.recommendation
            );

            setIsTargetConnect(
                true
            );

            console.log(
                "Response of migrated non container application: ",
                j
            );

            console.log(
                "this response of migration:",
                j
            );

            console.log(
                "this is message from migrate",
                j
            );
        } catch (e) {
            console.log(
                "Failed to do migration of single"
            );
        } finally {
            setIsDone(true);
            setIsTransferring(false);

            setLoadingNonContainerId(
                null
            );

            setSourceNonContainers(
                prev =>
                    (
                        Array.isArray(prev)
                            ? prev
                            : []
                    ).map(
                        app =>
                            app.pid === pid
                                ? {
                                    ...app,
                                    transferring:
                                        false
                                }
                                : app
                    )
            );

            setActiveNonContainerOperation(
                null
            );
        }
    }

    if (
        IsRunApplication &&
        applicationStatus
    ) {
        return (
            <RunStep
                setStep={setStep}
                target={targetVm}
                source={sourceCredential}
                applicationStatus={
                    applicationStatus
                }
                summary={summary}
                setRunStep={setRunStep}
            />
        );
    }

    /*
     * ============================================================
     * NON-CONTAINER -> CONTAINER STATE
     * ============================================================
     */

    const [
        isContainerizing,
        setIsContainerizing
    ] = useState(false);

    const [
        containerizedAppInfo,
        setContainerizedAppInfo
    ] = useState(null);

    /*
     * ============================================================
     * AUTOMATIC NON-CONTAINER -> CONTAINER MIGRATION
     * ============================================================
     *
     * Backend performs up to 5 automatic Containerfile repairs.
     *
     * When all 5 fail:
     *
     * {
     *     requires_user_edit: true,
     *     containerfile: "...",
     *     containerfile_name: "Containerfile",
     *     attempts: 5,
     *     application_transferred: true,
     *     ...
     * }
     *
     * is returned and the editor is opened.
     */

    async function handleNonContainerToContainerMigrate(
        pid,
        local,
        tech_stack
    ) {
        /*
         * Another transfer/containerization operation is
         * already running.
         */
        if (activeNonContainerOperation) {
            return;
        }

        setActiveNonContainerOperation(
            "containerize"
        );

        setLoadingNonContainerId(
            pid
        );

        setIsContainerizing(
            true
        );

        /*
         * Close an old editor before beginning a new automatic
         * migration.
         */
        setContainerfileEditor(
            prev => ({
                ...prev,
                open: false
            })
        );

        setSourceNonContainers(
            prev =>
                (
                    Array.isArray(prev)
                        ? prev
                        : []
                ).map(
                    app =>
                        app.pid === pid
                            ? {
                                ...app,
                                migratingToContainer:
                                    true,
                                transferring:
                                    false
                            }
                            : app
                )
        );

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/non-container-to-container-migrate`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body: JSON.stringify({
                            pid,
                            tech_stack,
                            source:
                                sourceCredential,
                            target:
                                targetVm,
                        }),
                    }
                );

            const j =
                await res.json();

            /*
             * ====================================================
             * AUTOMATIC MIGRATION SUCCESS
             * ====================================================
             */

            if (res.ok) {
                setContainerizedAppInfo(
                    j
                );

                setSourceNonContainers(
                    prev =>
                        (
                            Array.isArray(
                                prev
                            )
                                ? prev
                                : []
                        ).map(
                            app =>
                                app.pid === pid
                                    ? {
                                        ...app,
                                        containerized:
                                            true,
                                        migrationFailed:
                                            false,
                                        transferring:
                                            false,
                                        migratingToContainer:
                                            false
                                    }
                                    : app
                        )
                );

                alert(
                    "Container migration completed! Run command: " +
                    (
                        j.run_command ||
                        ""
                    )
                );

                return;
            }

            /*
             * ====================================================
             * 5 ATTEMPTS FAILED
             * ====================================================
             *
             * Backend returns the latest Containerfile/Dockerfile.
             */

            const canEdit =
                Boolean(
                    j.requires_user_edit ||
                    j.can_retry_with_edited_file ||
                    j.containerfile
                );

            if (
                canEdit &&
                j.containerfile
            ) {
                setContainerfileEditor({
                    open: true,

                    pid:
                        j.pid ??
                        pid,

                    port:
                        j.port ??
                        local ??
                        "",

                    fileName:
                        j.containerfile_name ||
                        j.dockerfile_name ||
                        "Containerfile",

                    content:
                        j.containerfile,

                    attempts:
                        j.attempts ||
                        5,

                    runtime:
                        j.container_runtime ||
                        j.runtime ||
                        "",

                    applicationTransferred:
                        j.application_transferred !==
                        false,

                    failureDetails:
                        j.failure_details ||
                        j.reason ||
                        j.error ||
                        null
                });

                setSourceNonContainers(
                    prev =>
                        (
                            Array.isArray(
                                prev
                            )
                                ? prev
                                : []
                        ).map(
                            app =>
                                app.pid === pid
                                    ? {
                                        ...app,
                                        migrationFailed:
                                            true,
                                        containerized:
                                            false,
                                        transferring:
                                            false,
                                        migratingToContainer:
                                            false,
                                        containerfileReadyForEdit:
                                            true
                                    }
                                    : app
                        )
                );

                alert(
                    `Automatic containerization failed after ${
                        j.attempts ||
                        5
                    } attempts. ` +
                    "The latest Containerfile/Dockerfile is ready to edit and run."
                );
            } else {
                /*
                 * Normal failure where backend did not provide
                 * a Containerfile.
                 */

                setSourceNonContainers(
                    prev =>
                        (
                            Array.isArray(
                                prev
                            )
                                ? prev
                                : []
                        ).map(
                            app =>
                                app.pid === pid
                                    ? {
                                        ...app,
                                        migrationFailed:
                                            true,
                                        containerized:
                                            false,
                                        transferring:
                                            false,
                                        migratingToContainer:
                                            false
                                    }
                                    : app
                        )
                );

                alert(
                    "Migration failed: " +
                    (
                        j.error ||
                        j.message ||
                        j.failure_details ||
                        "Unknown error"
                    )
                );
            }
        } catch (e) {
            setSourceNonContainers(
                prev =>
                    (
                        Array.isArray(prev)
                            ? prev
                            : []
                    ).map(
                        app =>
                            app.pid === pid
                                ? {
                                    ...app,
                                    migrationFailed:
                                        true,
                                    containerized:
                                        false,
                                    transferring:
                                        false,
                                    migratingToContainer:
                                        false
                                }
                                : app
                    )
            );

            alert(
                "Migration failed: " +
                e.message
            );
        } finally {
            setLoadingNonContainerId(
                null
            );

            setIsContainerizing(
                false
            );

            setActiveNonContainerOperation(
                null
            );
        }
    }

    /*
     * ============================================================
     * RUN USER-EDITED CONTAINERFILE
     * ============================================================
     *
     * IMPORTANT:
     *
     * This does NOT call the transfer API.
     *
     * The backend is expected to use the application that was
     * already transferred during the first containerization attempt.
     */

    async function runEditedContainerfile() {
        if (
            activeNonContainerOperation ||
            editedContainerfileRunning
        ) {
            return;
        }

        if (
            !containerfileEditor.pid
        ) {
            alert(
                "Application PID is missing."
            );

            return;
        }

        if (
            !containerfileEditor.content.trim()
        ) {
            alert(
                "Containerfile/Dockerfile cannot be empty."
            );

            return;
        }

        if (
            !containerfileEditor.port
        ) {
            alert(
                "Application port is required to run the edited Containerfile."
            );

            return;
        }

        setActiveNonContainerOperation(
            "edited-containerize"
        );

        setEditedContainerfileRunning(
            true
        );

        setLoadingNonContainerId(
            containerfileEditor.pid
        );

        try {
            const res =
                await fetch(
                    `${config.BASE_PATH}/api/non-container-to-container-run-edited`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json"
                        },
                        body: JSON.stringify({
                            pid:
                                containerfileEditor.pid,

                            port:
                                containerfileEditor.port,

                            containerfile:
                                containerfileEditor.content,

                            containerfile_name:
                                containerfileEditor.fileName,

                            target:
                                targetVm
                        })
                    }
                );

            const j =
                await res.json();

            /*
             * ====================================================
             * USER-EDITED FILE SUCCESS
             * ====================================================
             */

            if (res.ok) {
                setContainerizedAppInfo(
                    j
                );

                setSourceNonContainers(
                    prev =>
                        (
                            Array.isArray(
                                prev
                            )
                                ? prev
                                : []
                        ).map(
                            app =>
                                app.pid ===
                                containerfileEditor.pid
                                    ? {
                                        ...app,
                                        containerized:
                                            true,
                                        migrationFailed:
                                            false,
                                        transferring:
                                            false,
                                        migratingToContainer:
                                            false,
                                        containerfileReadyForEdit:
                                            false
                                    }
                                    : app
                        )
                );

                setContainerfileEditor(
                    prev => ({
                        ...prev,
                        open: false
                    })
                );

                setIsTargetConnect(
                    true
                );

                alert(
                    "Container started successfully! Run command: " +
                    (
                        j.run_command ||
                        ""
                    )
                );
            } else {
                /*
                 * Keep the editor open.
                 *
                 * If backend returns another/latest file,
                 * replace the editor content with it.
                 */

                setContainerfileEditor(
                    prev => ({
                        ...prev,

                        open: true,

                        content:
                            j.containerfile ||
                            prev.content,

                        fileName:
                            j.containerfile_name ||
                            prev.fileName,

                        attempts:
                            j.attempts ||
                            prev.attempts,

                        runtime:
                            j.container_runtime ||
                            j.runtime ||
                            prev.runtime,

                        failureDetails:
                            j.failure_details ||
                            j.reason ||
                            j.error ||
                            "Edited Containerfile failed."
                    })
                );

                alert(
                    "Edited Containerfile failed: " +
                    (
                        j.error ||
                        j.message ||
                        j.failure_details ||
                        "Unknown error"
                    )
                );
            }
        } catch (e) {
            setContainerfileEditor(
                prev => ({
                    ...prev,
                    open: true,
                    failureDetails:
                        e.message
                })
            );

            alert(
                "Failed to run edited Containerfile: " +
                e.message
            );
        } finally {
            setLoadingNonContainerId(
                null
            );

            setEditedContainerfileRunning(
                false
            );

            setActiveNonContainerOperation(
                null
            );
        }
    }

    /*
     * ============================================================
     * GLOBAL NON-CONTAINER OPERATION STATUS
     * ============================================================
     */

    const operationInProgress =
        activeNonContainerOperation !== null;

    return (
        <>
            {containerfileEditor.open && (
                <div className="row mb-3">
                    <div className="col-lg-12">
                        <div
                            className="card card-darken"
                            style={{
                                border:
                                    "1px solid #f0ad4e"
                            }}
                        >
                            <div
                                className="secondary-heading d-flex justify-content-between align-items-center"
                            >
                                <div
                                    className="d-flex align-items-center gap-2"
                                >
                                    <FileText
                                        size={22}
                                    />

                                    <h3
                                        style={{
                                            margin: 0
                                        }}
                                    >
                                        Edit{" "}
                                        {
                                            containerfileEditor.fileName ||
                                            "Containerfile"
                                        }
                                    </h3>
                                </div>

                                <button
                                    type="button"
                                    className="btn btn-sm btn-outline-secondary"
                                    onClick={() =>
                                        setContainerfileEditor(
                                            prev => ({
                                                ...prev,
                                                open: false
                                            })
                                        )
                                    }
                                    disabled={
                                        editedContainerfileRunning
                                    }
                                    title="Close editor"
                                >
                                    <X
                                        size={18}
                                    />
                                </button>
                            </div>

                            <div className="card-body">
                                <div className="mb-3">
                                    <div className="d-flex flex-wrap gap-3 small text-muted">
                                        <span>
                                            <strong>
                                                PID:
                                            </strong>{" "}
                                            {
                                                containerfileEditor.pid
                                            }
                                        </span>

                                        <span>
                                            <strong>
                                                Port:
                                            </strong>{" "}
                                            {
                                                containerfileEditor.port ||
                                                "Not detected"
                                            }
                                        </span>

                                        <span>
                                            <strong>
                                                Runtime:
                                            </strong>{" "}
                                            {
                                                containerfileEditor.runtime ||
                                                "Docker/Podman"
                                            }
                                        </span>

                                        <span>
                                            <strong>
                                                Automatic attempts:
                                            </strong>{" "}
                                            {
                                                containerfileEditor.attempts ||
                                                5
                                            }
                                        </span>
                                    </div>

                                    {containerfileEditor.failureDetails && (
                                        <div className="alert alert-warning mt-3 mb-0">
                                            <strong>
                                                Last failure:
                                            </strong>{" "}
                                            {
                                                String(
                                                    containerfileEditor.failureDetails
                                                )
                                            }
                                        </div>
                                    )}
                                </div>

                                <textarea
                                    value={
                                        containerfileEditor.content
                                    }
                                    onChange={e =>
                                        setContainerfileEditor(
                                            prev => ({
                                                ...prev,
                                                content:
                                                    e.target.value
                                            })
                                        )
                                    }
                                    spellCheck={false}
                                    disabled={
                                        editedContainerfileRunning
                                    }
                                    style={{
                                        width:
                                            "100%",
                                        minHeight:
                                            "420px",
                                        resize:
                                            "vertical",
                                        fontFamily:
                                            "monospace",
                                        fontSize:
                                            "13px",
                                        lineHeight:
                                            1.5,
                                        padding:
                                            "14px",
                                        borderRadius:
                                            "6px",
                                        border:
                                            "1px solid #555",
                                        background:
                                            "#111",
                                        color:
                                            "#f5f5f5"
                                    }}
                                />

                                <div className="d-flex justify-content-end align-items-center gap-2 mt-3">
                                    <button
                                        type="button"
                                        className="btn btn-secondary btn-sm"
                                        onClick={() =>
                                            setContainerfileEditor(
                                                prev => ({
                                                    ...prev,
                                                    open: false
                                                })
                                            )
                                        }
                                        disabled={
                                            editedContainerfileRunning
                                        }
                                    >
                                        Close
                                    </button>

                                    <button
                                        type="button"
                                        className="btn btn-success btn-sm d-flex align-items-center gap-2"
                                        onClick={
                                            runEditedContainerfile
                                        }
                                        disabled={
                                            operationInProgress ||
                                            editedContainerfileRunning
                                        }
                                    >
                                        {editedContainerfileRunning ? (
                                            <>
                                                <Loader2
                                                    size={
                                                        16
                                                    }
                                                    className="spin"
                                                />

                                                Building
                                                & Running...
                                            </>
                                        ) : (
                                            <>
                                                <Play
                                                    size={
                                                        16
                                                    }
                                                />

                                                Run Edited{" "}
                                                {
                                                    containerfileEditor.fileName ||
                                                    "Containerfile"
                                                }
                                            </>
                                        )}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <div className="row">
                <div className="col-lg-12">
                    <div className="card">
                        <div className="card-header">
                            <div className="title">
                                <span>
                                    <SendToBack
                                        size={24}
                                        className="orange-text"
                                    />
                                </span>

                                <h2>
                                    Transfer
                                </h2>
                            </div>
                        </div>

                        <div className="card-body">
                            <div className="card card-darken mb-3">
                                <div className="secondary-heading">
                                    <h3>
                                        Source VM Credentials
                                    </h3>
                                </div>

                                <div className="card-body pt-0">
                                    <div className="grid-2">
                                        <div className="form-group">
                                            <label>
                                                VM IP
                                            </label>

                                            <input
                                                className="form-control"
                                                type="text"
                                                name="ip"
                                                value={
                                                    sourceCredential?.host
                                                }
                                                disabled
                                            />
                                        </div>

                                        <div className="form-group">
                                            <label>
                                                Username
                                            </label>

                                            <input
                                                type="text"
                                                className="form-control"
                                                value={
                                                    sourceCredential?.user
                                                }
                                                name="username"
                                                disabled
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="card card-darken mb-3">
                                <div className="secondary-heading">
                                    <h3>
                                        Enter Target VM Credentials
                                    </h3>
                                </div>

                                <div className="card-body pt-0">
                                    <div className="grid-4">
                                        <div className="form-group">
                                            <label>
                                                VM IP
                                            </label>

                                            <input
                                                type="text"
                                                className="form-control"
                                                value={
                                                    targetVm.ip
                                                }
                                                name="ip"
                                                placeholder="Enter VM IP"
                                                onChange={
                                                    handleChange
                                                }
                                            />
                                        </div>

                                        <div className="form-group">
                                            <label>
                                                Username
                                            </label>

                                            <input
                                                type="text"
                                                className="form-control"
                                                value={
                                                    targetVm.TargetUsername
                                                }
                                                name="TargetUsername"
                                                placeholder="Enter UserName"
                                                onChange={
                                                    handleChange
                                                }
                                            />
                                        </div>

                                        <div className="form-group">
                                            <label>
                                                Password
                                            </label>

                                            <input
                                                className="form-control"
                                                value={
                                                    targetVm.TargetPassword
                                                }
                                                name="TargetPassword"
                                                type="password"
                                                placeholder="Enter password"
                                                onChange={
                                                    handleChange
                                                }
                                            />
                                        </div>

                                        <div className="form-group">
                                            <label>
                                                Sudo Password
                                            </label>

                                            <input
                                                className="form-control"
                                                value={
                                                    targetVm.TargetSudoPassword
                                                }
                                                name="TargetSudoPassword"
                                                placeholder="Enter Sudo Password"
                                                type="password"
                                                onChange={
                                                    handleChange
                                                }
                                            />
                                        </div>
                                    </div>

                                    <div className="d-flex justify-content-end mt-3 gap-2">
                                        <button
                                            type="submit"
                                            className="btn btn-orange btn-sm"
                                            onClick={
                                                testSshConnection
                                            }
                                        >
                                            Connect
                                        </button>

                                        {isConnected && (
                                            <button
                                                type="submit"
                                                className="btn btn-primary"
                                                style={{
                                                    background:
                                                        "#4E84C4"
                                                }}
                                                onClick={async () => {
                                                    setLoading(
                                                        true
                                                    );

                                                    try {
                                                        const get_source_containers =
                                                            async () => {
                                                                const res =
                                                                    await fetch(
                                                                        `${config.BASE_PATH}/api/get-containers`,
                                                                        {
                                                                            method:
                                                                                "POST",
                                                                            headers:
                                                                                {
                                                                                    "Content-Type":
                                                                                        "application/json"
                                                                                },
                                                                            body:
                                                                                JSON.stringify(
                                                                                    {
                                                                                        source:
                                                                                            sourceCredential
                                                                                    }
                                                                                )
                                                                        }
                                                                    );

                                                                const cont =
                                                                    await res.json();

                                                                if (
                                                                    cont.containers
                                                                ) {
                                                                    setContainers(
                                                                        cont.containers
                                                                    );
                                                                }
                                                            };

                                                        const getSourceNonContainers =
                                                            async () => {
                                                                const res =
                                                                    await fetch(
                                                                        `${config.BASE_PATH}/api/get-source-non-container`,
                                                                        {
                                                                            method:
                                                                                "POST",
                                                                            headers:
                                                                                {
                                                                                    "Content-Type":
                                                                                        "application/json"
                                                                                },
                                                                            body:
                                                                                JSON.stringify(
                                                                                    {
                                                                                        source:
                                                                                            sourceCredential
                                                                                    }
                                                                                )
                                                                        }
                                                                    );

                                                                const cont =
                                                                    await res.json();

                                                                if (
                                                                    cont.source_non_containerized
                                                                ) {
                                                                    setSourceNonContainers(
                                                                        cont.source_non_containerized
                                                                    );
                                                                }
                                                            };

                                                        await get_source_containers();
                                                        await getSourceNonContainers();
                                                    } catch (e) {
                                                        console.log(
                                                            "failed to fetch non containers applications:",
                                                            e
                                                        );
                                                    } finally {
                                                        setLoading(
                                                            false
                                                        );
                                                    }
                                                }}
                                            >
                                                Next Step
                                            </button>
                                        )}
                                    </div>

                                    {sshStatus && (
                                        <div
                                            style={{
                                                color:
                                                    "#645b5b"
                                            }}
                                            className={`ssh-status ${sshStatus}`}
                                        >
                                            <p
                                                style={{
                                                    margin: 0
                                                }}
                                            >
                                                <span
                                                    style={{
                                                        fontSize:
                                                            "15px",
                                                        fontWeight:
                                                            "bold"
                                                    }}
                                                >
                                                    Connection Status:{" "}
                                                </span>

                                                {sshStatus ===
                                                    "connecting" && (
                                                    <span
                                                        style={{
                                                            color:
                                                                "#d3bd77"
                                                        }}
                                                    >
                                                        Connecting...
                                                    </span>
                                                )}

                                                {sshStatus ===
                                                    "connected" && (
                                                    <span
                                                        style={{
                                                            color:
                                                                "#5dcc47"
                                                        }}
                                                    >
                                                        Connected
                                                    </span>
                                                )}

                                                {sshStatus ===
                                                    "error" && (
                                                    <span
                                                        style={{
                                                            color:
                                                                "#cc4747"
                                                        }}
                                                    >
                                                        {sshError}
                                                    </span>
                                                )}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/*
                            ==================================================
                            PREREQUISITE RESULT
                            ==================================================
                            */}

                            {/*
                            {isConnected && (
                                <div className="card card-darken">
                                    <div className="secondary-heading">
                                        <h3>
                                            Pre-requisite Check Result
                                        </h3>
                                    </div>

                                    <div className="card-body pt-0">
                                        <div className="grid3">
                                            <div className="prerequisitecheck">
                                                {prereqLoading ? (
                                                    <div
                                                        style={{
                                                            textAlign:
                                                                "center",
                                                            padding:
                                                                "40px"
                                                        }}
                                                    >
                                                        <div className="d-loader"></div>
                                                        <p>
                                                            Checking...
                                                        </p>
                                                    </div>
                                                ) : (
                                                    <>
                                                        <div
                                                            style={{
                                                                display:
                                                                    "grid",
                                                                gridTemplateColumns:
                                                                    "repeat(3, 1fr)",
                                                                gap:
                                                                    "12px 40px",
                                                                padding:
                                                                    "10px 20px"
                                                            }}
                                                        >
                                                            {pidGroups.map(
                                                                ([
                                                                    pid,
                                                                    items
                                                                ]) => (
                                                                    <div
                                                                        key={
                                                                            pid
                                                                        }
                                                                        style={{
                                                                            border:
                                                                                "1px solid #ccc",
                                                                            borderRadius:
                                                                                "8px",
                                                                            padding:
                                                                                "15px"
                                                                        }}
                                                                    >
                                                                        <h5 className="text-start modal-title">
                                                                            PID:
                                                                            {" "}
                                                                            {
                                                                                pid
                                                                            }
                                                                        </h5>

                                                                        {items.map(
                                                                            (
                                                                                item,
                                                                                index
                                                                            ) => (
                                                                                <Row
                                                                                    key={
                                                                                        index
                                                                                    }
                                                                                    item={
                                                                                        item
                                                                                    }
                                                                                />
                                                                            )
                                                                        )}
                                                                    </div>
                                                                )
                                                            )}
                                                        </div>

                                                        <div className="d-flex justify-content-end mt-3 gap-2">
                                                            <button
                                                                type="submit"
                                                                className="btn btn-primary"
                                                                style={{
                                                                    background:
                                                                        "#4E84C4"
                                                                }}
                                                                onClick={async () => {
                                                                    setLoading(
                                                                        true
                                                                    );

                                                                    try {
                                                                        const get_source_containers =
                                                                            async () => {
                                                                                const res =
                                                                                    await fetch(
                                                                                        `${config.BASE_PATH}/api/get-containers`,
                                                                                        {
                                                                                            method:
                                                                                                "POST",
                                                                                            headers:
                                                                                                {
                                                                                                    "Content-Type":
                                                                                                        "application/json"
                                                                                                },
                                                                                            body:
                                                                                                JSON.stringify(
                                                                                                    {
                                                                                                        source:
                                                                                                            sourceCredential
                                                                                                    }
                                                                                                )
                                                                                        }
                                                                                    );

                                                                                const cont =
                                                                                    await res.json();

                                                                                if (
                                                                                    cont.containers
                                                                                ) {
                                                                                    setContainers(
                                                                                        cont.containers
                                                                                    );
                                                                                }
                                                                            };

                                                                        const getSourceNonContainers =
                                                                            async () => {
                                                                                const res =
                                                                                    await fetch(
                                                                                        `${config.BASE_PATH}/api/get-source-non-container`,
                                                                                        {
                                                                                            method:
                                                                                                "POST",
                                                                                            headers:
                                                                                                {
                                                                                                    "Content-Type":
                                                                                                        "application/json"
                                                                                                },
                                                                                            body:
                                                                                                JSON.stringify(
                                                                                                    {
                                                                                                        source:
                                                                                                            sourceCredential
                                                                                                    }
                                                                                                )
                                                                                        }
                                                                                    );

                                                                                const cont =
                                                                                    await res.json();

                                                                                if (
                                                                                    cont.source_non_containerized
                                                                                ) {
                                                                                    setSourceNonContainers(
                                                                                        cont.source_non_containerized
                                                                                    );
                                                                                }
                                                                            };

                                                                        await get_source_containers();
                                                                        await getSourceNonContainers();
                                                                    } catch (e) {
                                                                        console.log(
                                                                            "failed to fetch non containers applications:",
                                                                            e
                                                                        );
                                                                    } finally {
                                                                        setLoading(
                                                                            false
                                                                        );
                                                                    }
                                                                }}
                                                            >
                                                                Next Step
                                                            </button>
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                            */}

                            {loading ? (
                                <div className="d-loader"></div>
                            ) : (
                                <>
                                    <div>
                                        {isStatusContainerizedApplication && (
                                            <div
                                                className={
                                                    styles.overlay
                                                }
                                            >
                                                <div
                                                    className={
                                                        styles.popup
                                                    }
                                                >
                                                    <div></div>

                                                    <button
                                                        className={
                                                            styles.close
                                                        }
                                                        onClick={() =>
                                                            setIsStatusContainerizedApplication(
                                                                false
                                                            )
                                                        }
                                                    >
                                                        <X />
                                                    </button>

                                                    <div>
                                                        <p
                                                            style={{
                                                                color:
                                                                    "green",
                                                                textAlign:
                                                                    "center",
                                                                fontSize:
                                                                    "20px"
                                                            }}
                                                        >
                                                            Container Migration Completed
                                                            <CheckCircle />
                                                        </p>
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        {isOpen && (
                                            <div
                                                className={
                                                    styles.overlay
                                                }
                                            >
                                                <div
                                                    className={
                                                        styles.popup
                                                    }
                                                >
                                                    <div>
                                                        {isTransferring &&
                                                            !isDone && (
                                                                <>
                                                                    <p
                                                                        style={{
                                                                            color:
                                                                                "black",
                                                                            margin:
                                                                                "12px"
                                                                        }}
                                                                    >
                                                                        Transferring application (
                                                                        {
                                                                            transferringName
                                                                        }
                                                                        ) deployed on
                                                                        the{" "}
                                                                        {
                                                                            transferPort
                                                                        }{" "}
                                                                        from source machine ip{" "}
                                                                        {
                                                                            sourceCredential.host
                                                                        }{" "}
                                                                        to target machine ip{" "}
                                                                        {
                                                                            targetVm.ip
                                                                        }
                                                                    </p>

                                                                    <div
                                                                        className={
                                                                            stylesT.movingLine
                                                                        }
                                                                    ></div>
                                                                </>
                                                            )}

                                                        {isDone &&
                                                            !isTransferring && (
                                                                <>
                                                                    <div>
                                                                        <p
                                                                            style={{
                                                                                color:
                                                                                    "green",
                                                                                textAlign:
                                                                                    "center",
                                                                                fontSize:
                                                                                    "20px"
                                                                            }}
                                                                        >
                                                                            Transfer Completed
                                                                            <CheckCircle />
                                                                        </p>
                                                                    </div>
                                                                </>
                                                            )}
                                                    </div>

                                                    <button
                                                        className={
                                                            styles.close
                                                        }
                                                        onClick={() =>
                                                            setIsOpen(
                                                                false
                                                            )
                                                        }
                                                    >
                                                        <X />
                                                    </button>
                                                </div>
                                            </div>
                                        )}

                                        {isRun && (
                                            <div
                                                className={
                                                    styles.overlay
                                                }
                                            >
                                                <div
                                                    className={
                                                        styles.popup
                                                    }
                                                >
                                                    <div
                                                        style={{
                                                            width:
                                                                "inherit"
                                                        }}
                                                    >
                                                        <textarea
                                                            className="form-control mb-3"
                                                            style={{
                                                                width:
                                                                    "100%",
                                                                flex:
                                                                    1,
                                                                resize:
                                                                    "none"
                                                            }}
                                                            value={
                                                                nonContainerFinalResult
                                                            }
                                                            onChange={e =>
                                                                setnonContainerFinalResult(
                                                                    e.target.value
                                                                )
                                                            }
                                                            rows={
                                                                4
                                                            }
                                                        ></textarea>

                                                        <span>
                                                            <button
                                                                className="btn btn-primary btn-sm"
                                                                onClick={
                                                                    runNonContainer
                                                                }
                                                                disabled={
                                                                    isRunContainer
                                                                }
                                                            >
                                                                {isRunContainer
                                                                    ? "Running..."
                                                                    : "Run"}
                                                            </button>
                                                        </span>
                                                    </div>

                                                    <button
                                                        className={
                                                            styles.close
                                                        }
                                                        onClick={() =>
                                                            setIsRun(
                                                                false
                                                            )
                                                        }
                                                    >
                                                        <X />
                                                    </button>
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    <div className="cloud-card">
                                        {containers?.length >
                                            0 && (
                                            <>
                                                <div className="card-body">
                                                    <div className="card card-darken mb-3">
                                                        <div className="secondary-heading">
                                                            <h3>
                                                                Migrate Containarized Application
                                                            </h3>
                                                        </div>

                                                        <div className="row">
                                                            <div className="card-body">
                                                                <div className="card card-darken">
                                                                    <div className="secondary-heading">
                                                                        <h3>
                                                                            Source VM (
                                                                            {
                                                                                sourceCredential?.host
                                                                            }
                                                                            )
                                                                        </h3>
                                                                    </div>

                                                                    <div className="card-body pt-0">
                                                                        <div className="row">
                                                                            <div className="col-lg-12">
                                                                                <div className="table-responsive">
                                                                                    <table className="data-table table mb-0">
                                                                                        <thead>
                                                                                            <tr>
                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Name
                                                                                                    </div>
                                                                                                </th>

                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Image
                                                                                                    </div>
                                                                                                </th>

                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Action
                                                                                                    </div>
                                                                                                </th>
                                                                                            </tr>
                                                                                        </thead>

                                                                                        <tbody>
                                                                                            {containers?.map(
                                                                                                (
                                                                                                    [
                                                                                                        name,
                                                                                                        img,
                                                                                                        host_port,
                                                                                                        container_port
                                                                                                    ],
                                                                                                    index
                                                                                                ) => (
                                                                                                    <tr
                                                                                                        key={
                                                                                                            index
                                                                                                        }
                                                                                                    >
                                                                                                        <td>
                                                                                                            {
                                                                                                                name
                                                                                                            }
                                                                                                        </td>

                                                                                                        <td>
                                                                                                            {
                                                                                                                img
                                                                                                            }
                                                                                                        </td>

                                                                                                        <td>
                                                                                                            <button
                                                                                                                className="btn btn-primary btn-sm"
                                                                                                                key={
                                                                                                                    name
                                                                                                                }
                                                                                                                onClick={() =>
                                                                                                                    handleMigrate(
                                                                                                                        name,
                                                                                                                        host_port,
                                                                                                                        container_port,
                                                                                                                        img
                                                                                                                    )
                                                                                                                }
                                                                                                                disabled={
                                                                                                                    loadingId ===
                                                                                                                    name
                                                                                                                }
                                                                                                            >
                                                                                                                {loadingId ===
                                                                                                                name
                                                                                                                    ? "Migrating..."
                                                                                                                    : "Migrate This Container"}
                                                                                                            </button>
                                                                                                        </td>
                                                                                                    </tr>
                                                                                                )
                                                                                            )}
                                                                                        </tbody>
                                                                                    </table>
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>

                                                            <div className="card-body">
                                                                <div className="card card-darken">
                                                                    <div className="secondary-heading">
                                                                        <h3 className="secondary-heading">
                                                                            Target VM{" "}
                                                                            {
                                                                                targetVm?.ip && (
                                                                                    <span>
                                                                                        (
                                                                                        {
                                                                                            targetVm?.ip
                                                                                        }
                                                                                        )
                                                                                    </span>
                                                                                )
                                                                            }

                                                                            {sshStatus ===
                                                                                "connected" && (
                                                                                <span
                                                                                    style={{
                                                                                        alignItems:
                                                                                            "right",
                                                                                        marginLeft:
                                                                                            "20px"
                                                                                    }}
                                                                                >
                                                                                    <button
                                                                                        className="btn btn-primary btn-sm"
                                                                                        onClick={
                                                                                            get_target_containers
                                                                                        }
                                                                                    >
                                                                                        Load Container
                                                                                    </button>
                                                                                </span>
                                                                            )}
                                                                        </h3>
                                                                    </div>

                                                                    <div className="card-body pt-0">
                                                                        <div className="row">
                                                                            <div className="col-lg-12">
                                                                                <div className="table-responsive">
                                                                                    <table className="data-table table mb-0">
                                                                                        <thead>
                                                                                            <tr>
                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Name
                                                                                                    </div>
                                                                                                </th>

                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Image
                                                                                                    </div>
                                                                                                </th>

                                                                                                <th scope="col">
                                                                                                    <div className="d-flex align-items-center">
                                                                                                        Created At
                                                                                                    </div>
                                                                                                </th>
                                                                                            </tr>
                                                                                        </thead>

                                                                                        <tbody>
                                                                                            {target_containers
                                                                                                ? target_containers.map(
                                                                                                    (
                                                                                                        [
                                                                                                            name,
                                                                                                            img,
                                                                                                            host_port,
                                                                                                            container_port,
                                                                                                            startedAt,
                                                                                                            createdAt
                                                                                                        ],
                                                                                                        index
                                                                                                    ) => (
                                                                                                        <tr
                                                                                                            key={
                                                                                                                index
                                                                                                            }
                                                                                                        >
                                                                                                            <td>
                                                                                                                {
                                                                                                                    name
                                                                                                                }
                                                                                                            </td>

                                                                                                            <td>
                                                                                                                {
                                                                                                                    img
                                                                                                                }
                                                                                                            </td>

                                                                                                            <td>
                                                                                                                {
                                                                                                                    createdAt
                                                                                                                }
                                                                                                            </td>
                                                                                                        </tr>
                                                                                                    )
                                                                                                )
                                                                                                : (
                                                                                                    <tr>
                                                                                                        <td
                                                                                                            colSpan={
                                                                                                                3
                                                                                                            }
                                                                                                        >
                                                                                                            <div className="no-data ver">
                                                                                                                Load Container to see data
                                                                                                            </div>
                                                                                                        </td>
                                                                                                    </tr>
                                                                                                )}
                                                                                        </tbody>
                                                                                    </table>
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        )}

                                        {/*
                                        ============================================================
                                        NON-CONTAINER APPLICATIONS
                                        ============================================================
                                        */}

                                        {sourceNonContainers?.length >
                                            0 && (
                                            <div className="card-body">
                                                <div className="card card-darken mb-3">
                                                    <div className="secondary-heading">
                                                        <h3>
                                                            Migrate Non-Containarized Application
                                                        </h3>
                                                    </div>

                                                    <div className="row">
                                                        <div className="card-body">
                                                            <div className="card card-darken">
                                                                <div className="secondary-heading">
                                                                    <h3>
                                                                        Source VM (
                                                                        {
                                                                            sourceCredential?.host
                                                                        }
                                                                        )
                                                                    </h3>
                                                                </div>

                                                                <div className="card-body pt-0">
                                                                    <div className="row">
                                                                        <div className="col-lg-12">
                                                                            <div className="table-responsive">
                                                                                <table className="data-table table mb-0">
                                                                                    <thead>
                                                                                        <tr>
                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    IP
                                                                                                </div>
                                                                                            </th>

                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    LLM Generated Application Summary
                                                                                                </div>
                                                                                            </th>

                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    Transfer
                                                                                                </div>
                                                                                            </th>

                                                                                            <th>
                                                                                                Migrate to Container
                                                                                            </th>
                                                                                        </tr>
                                                                                    </thead>

                                                                                    <tbody>
                                                                                        {sourceNonContainers?.map(
                                                                                            (
                                                                                                app,
                                                                                                i
                                                                                            ) => (
                                                                                                <tr
                                                                                                    key={
                                                                                                        i
                                                                                                    }
                                                                                                >
                                                                                                    <td>
                                                                                                        {
                                                                                                            app.Local
                                                                                                        }
                                                                                                    </td>

                                                                                                    <td>
                                                                                                        {
                                                                                                            app.tech_stack
                                                                                                        }
                                                                                                    </td>

                                                                                                    <td>
                                                                                                        <button
                                                                                                            className="btn btn-primary btn-sm"
                                                                                                            key={
                                                                                                                i
                                                                                                            }
                                                                                                            onClick={() =>
                                                                                                                handleNonContainerizedMigrate(
                                                                                                                    app.pid,
                                                                                                                    app.Local
                                                                                                                )
                                                                                                            }
                                                                                                            disabled={
                                                                                                                operationInProgress ||
                                                                                                                loadingNonContainerId ===
                                                                                                                    app.pid
                                                                                                            }
                                                                                                        >
                                                                                                            {activeNonContainerOperation ===
                                                                                                                "transfer" &&
                                                                                                            loadingNonContainerId ===
                                                                                                                app.pid
                                                                                                                ? "Transferring..."
                                                                                                                : "Transfer"}
                                                                                                        </button>
                                                                                                    </td>

                                                                                                    <td>
                                                                                                        {app.containerized ? (
                                                                                                            <span className="text-success fw-bold d-flex align-items-center gap-2">
                                                                                                                <CheckCircle
                                                                                                                    size={
                                                                                                                        18
                                                                                                                    }
                                                                                                                />
                                                                                                                Migrated
                                                                                                            </span>
                                                                                                        ) : app.migrationFailed ? (
                                                                                                            <div className="d-flex align-items-center gap-2">
                                                                                                                <span className="text-danger fw-bold">
                                                                                                                    Failed
                                                                                                                </span>

                                                                                                                <button
                                                                                                                    className="btn btn-warning btn-sm"
                                                                                                                    onClick={() =>
                                                                                                                        handleNonContainerToContainerMigrate(
                                                                                                                            app.pid,
                                                                                                                            app.Local,
                                                                                                                            app.tech_stack
                                                                                                                        )
                                                                                                                    }
                                                                                                                    disabled={
                                                                                                                        operationInProgress ||
                                                                                                                        loadingNonContainerId ===
                                                                                                                            app.pid
                                                                                                                    }
                                                                                                                >
                                                                                                                    {activeNonContainerOperation ===
                                                                                                                        "containerize" &&
                                                                                                                    loadingNonContainerId ===
                                                                                                                        app.pid
                                                                                                                        ? "Retrying..."
                                                                                                                        : "Try Again"}
                                                                                                                </button>
                                                                                                            </div>
                                                                                                        ) : (
                                                                                                            <button
                                                                                                                className="btn btn-success btn-sm"
                                                                                                                onClick={() =>
                                                                                                                    handleNonContainerToContainerMigrate(
                                                                                                                        app.pid,
                                                                                                                        app.Local,
                                                                                                                        app.tech_stack
                                                                                                                    )
                                                                                                                }
                                                                                                                disabled={
                                                                                                                    operationInProgress ||
                                                                                                                    loadingNonContainerId ===
                                                                                                                        app.pid
                                                                                                                }
                                                                                                            >
                                                                                                                {activeNonContainerOperation ===
                                                                                                                    "containerize" &&
                                                                                                                loadingNonContainerId ===
                                                                                                                    app.pid
                                                                                                                    ? "Migrating..."
                                                                                                                    : "Migrate to Container"}
                                                                                                            </button>
                                                                                                        )}
                                                                                                    </td>
                                                                                                </tr>
                                                                                            )
                                                                                        )}
                                                                                    </tbody>
                                                                                </table>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        </div>

                                                        <div className="card-body">
                                                            <div className="card card-darken">
                                                                <div className="secondary-heading">
                                                                    <h3>
                                                                        Target VM{" "}
                                                                        {
                                                                            targetVm?.ip && (
                                                                                <span>
                                                                                    (
                                                                                    {
                                                                                        targetVm?.ip
                                                                                    }
                                                                                    )
                                                                                </span>
                                                                            )
                                                                        }
                                                                    </h3>
                                                                </div>

                                                                <div className="card-body pt-0">
                                                                    <div className="row">
                                                                        <div className="col-lg-12">
                                                                            <div className="table-responsive">
                                                                                <table className="data-table table mb-0">
                                                                                    <thead>
                                                                                        <tr>
                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    Address
                                                                                                </div>
                                                                                            </th>

                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    Peer
                                                                                                </div>
                                                                                            </th>

                                                                                            <th scope="col">
                                                                                                <div className="d-flex align-items-center">
                                                                                                    Status
                                                                                                </div>
                                                                                            </th>
                                                                                        </tr>
                                                                                    </thead>

                                                                                    <tbody>
                                                                                        {targetNonContainers?.map(
                                                                                            (
                                                                                                app,
                                                                                                i
                                                                                            ) => (
                                                                                                <tr
                                                                                                    key={
                                                                                                        i
                                                                                                    }
                                                                                                >
                                                                                                    <td>
                                                                                                        {
                                                                                                            app.Local
                                                                                                        }
                                                                                                    </td>

                                                                                                    <td>
                                                                                                        {
                                                                                                            app.Peer
                                                                                                        }
                                                                                                    </td>

                                                                                                    <td>
                                                                                                        Running
                                                                                                    </td>
                                                                                                </tr>
                                                                                            )
                                                                                        )}

                                                                                        {nonContainerFinalResult && (
                                                                                            <tr>
                                                                                                <td>
                                                                                                    {
                                                                                                        pathLocation
                                                                                                    }
                                                                                                </td>

                                                                                                <td>
                                                                                                    __
                                                                                                </td>

                                                                                                <td>
                                                                                                    <button
                                                                                                        onClick={() =>
                                                                                                            setIsRun(
                                                                                                                true
                                                                                                            )
                                                                                                        }
                                                                                                        className="btn btn-success btn-sm"
                                                                                                    >
                                                                                                        Run
                                                                                                    </button>
                                                                                                </td>
                                                                                            </tr>
                                                                                        )}
                                                                                    </tbody>
                                                                                </table>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {(
                                        containers?.length <=
                                            0 &&
                                        sourceNonContainers?.length <=
                                            0
                                    ) && (
                                        <div className="card">
                                            <div className="card-body pt-1">
                                                <div className="no-data">
                                                    No Application found
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
