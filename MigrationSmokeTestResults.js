
import React, { useEffect, useMemo, useState } from "react";
import {
    Activity,
    AlertCircle,
    AlertTriangle,
    CheckCircle2,
    ChevronDown,
    ChevronRight,
    Clock3,
    Container,
    Copy,
    Download,
    LoaderCircle,
    Network,
    Play,
    RefreshCw,
    Server,
    ShieldCheck,
    Terminal,
    XCircle,
    CircleHelp,
} from "lucide-react";

const MIGRATION_TYPES = [
    {
        value: "non_container",
        label: "Non-container migration",
        description: "Verify the migrated application process and service.",
        icon: Server,
    },
    {
        value: "container",
        label: "Container migration",
        description: "Verify the migrated container and its exposed service.",
        icon: Container,
    },
    {
        value: "non_container_to_container",
        label: "Non-container → container",
        description: "Verify the Podman/Docker container created from the application.",
        icon: Activity,
    },
];

const STATUS_META = {
    passed: {
        label: "Passed",
        color: "#15803d",
        background: "#dcfce7",
        icon: CheckCircle2,
    },
    failed: {
        label: "Failed",
        color: "#b91c1c",
        background: "#fee2e2",
        icon: XCircle,
    },
    warning: {
        label: "Warning",
        color: "#a16207",
        background: "#fef3c7",
        icon: AlertTriangle,
    },
    skipped: {
        label: "Skipped",
        color: "#64748b",
        background: "#f1f5f9",
        icon: CircleHelp,
    },
};

const styles = {
    wrapper: {
        width: "100%",
        color: "#0f172a",
        fontFamily: "inherit",
        boxSizing: "border-box",
    },
    panel: {
        border: "1px solid #e2e8f0",
        borderRadius: 14,
        background: "#ffffff",
        overflow: "hidden",
        boxShadow: "0 3px 12px rgba(15,23,42,0.04)",
    },
    header: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
        padding: "20px 22px",
        borderBottom: "1px solid #e2e8f0",
        flexWrap: "wrap",
    },
    titleRow: {
        display: "flex",
        alignItems: "center",
        gap: 10,
    },
    title: {
        fontSize: 18,
        fontWeight: 700,
        margin: 0,
        color: "#0f172a",
    },
    subtitle: {
        color: "#64748b",
        fontSize: 13,
        lineHeight: 1.6,
        margin: "7px 0 0",
    },
    section: {
        padding: 22,
        borderBottom: "1px solid #e2e8f0",
    },
    label: {
        display: "block",
        color: "#334155",
        fontSize: 12,
        fontWeight: 650,
        marginBottom: 7,
    },
    input: {
        width: "100%",
        minWidth: 0,
        boxSizing: "border-box",
        border: "1px solid #cbd5e1",
        borderRadius: 8,
        padding: "10px 11px",
        color: "#0f172a",
        background: "#fff",
        fontSize: 13,
        outlineOffset: 2,
    },
    select: {
        width: "100%",
        boxSizing: "border-box",
        border: "1px solid #cbd5e1",
        borderRadius: 8,
        padding: "10px 11px",
        color: "#0f172a",
        background: "#fff",
        fontSize: 13,
    },
    grid: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 14,
    },
    migrationOption: {
        border: "1px solid #cbd5e1",
        borderRadius: 10,
        padding: 13,
        cursor: "pointer",
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        minWidth: 0,
        background: "#fff",
        color: "#334155",
        textAlign: "left",
    },
    button: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        border: "1px solid #cbd5e1",
        borderRadius: 8,
        padding: "9px 13px",
        fontSize: 13,
        fontWeight: 650,
        cursor: "pointer",
        background: "#fff",
        color: "#334155",
    },
    primaryButton: {
        background: "#ea580c",
        color: "#fff",
        border: "1px solid #ea580c",
    },
    disabledButton: {
        opacity: 0.55,
        cursor: "not-allowed",
    },
    summaryGrid: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))",
        gap: 12,
        marginBottom: 18,
    },
    summaryCard: {
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        padding: 14,
        background: "#fff",
    },
    summaryLabel: {
        color: "#64748b",
        fontSize: 12,
        marginBottom: 8,
    },
    summaryValue: {
        fontSize: 25,
        lineHeight: 1.2,
        fontWeight: 750,
        color: "#0f172a",
    },
    resultRow: {
        border: "1px solid #e2e8f0",
        borderRadius: 10,
        marginBottom: 10,
        overflow: "hidden",
        background: "#fff",
    },
    resultButton: {
        display: "flex",
        alignItems: "center",
        width: "100%",
        gap: 12,
        padding: "14px 15px",
        border: 0,
        background: "transparent",
        cursor: "pointer",
        textAlign: "left",
        color: "#0f172a",
    },
    resultDetails: {
        borderTop: "1px solid #e2e8f0",
        padding: 15,
        color: "#475569",
        fontSize: 12,
        lineHeight: 1.7,
        overflowWrap: "anywhere",
    },
    code: {
        display: "block",
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        background: "#0f172a",
        color: "#e2e8f0",
        borderRadius: 8,
        padding: 12,
        fontSize: 12,
        lineHeight: 1.6,
        maxHeight: 260,
        overflow: "auto",
        marginTop: 8,
    },
    muted: {
        fontSize: 12,
        color: "#64748b",
        lineHeight: 1.6,
    },
    errorBox: {
        border: "1px solid #fecaca",
        background: "#fef2f2",
        color: "#991b1b",
        borderRadius: 9,
        padding: 13,
        marginBottom: 14,
        fontSize: 13,
        lineHeight: 1.6,
    },
    empty: {
        border: "1px dashed #cbd5e1",
        borderRadius: 10,
        padding: "30px 16px",
        textAlign: "center",
        color: "#64748b",
        background: "#f8fafc",
    },
};

function StatusBadge({ status }) {
    const meta = STATUS_META[status] || STATUS_META.skipped;
    const Icon = meta.icon;

    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                flexShrink: 0,
                padding: "4px 8px",
                borderRadius: 20,
                fontSize: 11,
                fontWeight: 700,
                color: meta.color,
                background: meta.background,
            }}
        >
            <Icon size={13} />
            {meta.label}
        </span>
    );
}

function SummaryCard({ label, value, color }) {
    return (
        <div style={styles.summaryCard}>
            <div style={styles.summaryLabel}>{label}</div>
            <div
                style={{
                    ...styles.summaryValue,
                    color: color || "#0f172a",
                }}
            >
                {value}
            </div>
        </div>
    );
}

function SmokeTestResultRow({ result, index }) {
    const [expanded, setExpanded] = useState(
        result.status === "failed"
    );

    const meta = STATUS_META[result.status] || STATUS_META.skipped;
    const Icon = meta.icon;

    return (
        <div style={styles.resultRow} key={`${result.name}-${index}`}>
            <button
                type="button"
                style={styles.resultButton}
                onClick={() => setExpanded((previous) => !previous)}
                aria-expanded={expanded}
            >
                <Icon
                    size={19}
                    color={meta.color}
                    style={{ flexShrink: 0 }}
                />

                <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                        style={{
                            fontSize: 13,
                            fontWeight: 700,
                            overflowWrap: "anywhere",
                        }}
                    >
                        {result.name || "Smoke test"}
                    </div>

                    <div
                        style={{
                            ...styles.muted,
                            marginTop: 4,
                        }}
                    >
                        {result.message || "No message returned."}
                    </div>
                </div>

                {Number.isFinite(Number(result.duration_ms)) &&
                    Number(result.duration_ms) > 0 && (
                        <span
                            style={{
                                ...styles.muted,
                                whiteSpace: "nowrap",
                            }}
                        >
                            {result.duration_ms} ms
                        </span>
                    )}

                <StatusBadge status={result.status} />

                {expanded ? (
                    <ChevronDown size={16} />
                ) : (
                    <ChevronRight size={16} />
                )}
            </button>

            {expanded && (
                <div style={styles.resultDetails}>
                    <strong>Details</strong>
                    <div style={{ marginTop: 5 }}>
                        {result.details || "No additional details were returned."}
                    </div>
                </div>
            )}
        </div>
    );
}

export default function MigrationSmokeTestResults({
    target,
    application = {},
    migrationType: initialMigrationType = "non_container",
    apiBasePath = "",
    onComplete,
}) {
    const [migrationType, setMigrationType] = useState(
        initialMigrationType
    );
    const [pid, setPid] = useState(application.pid ?? "");
    const [containerName, setContainerName] = useState(
        application.container_name ?? application.name ?? ""
    );
    const [port, setPort] = useState(application.port ?? "");
    const [checkHttp, setCheckHttp] = useState(true);

    const [loading, setLoading] = useState(false);
    const [report, setReport] = useState(null);
    const [error, setError] = useState("");
    const [expandedAll, setExpandedAll] = useState(false);

    useEffect(() => {
        setMigrationType(initialMigrationType);
    }, [initialMigrationType]);

    useEffect(() => {
        setPid(application.pid ?? "");
        setContainerName(
            application.container_name ?? application.name ?? ""
        );
        setPort(application.port ?? "");
    }, [
        application.pid,
        application.container_name,
        application.name,
        application.port,
    ]);

    const selectedMigration = useMemo(
        () =>
            MIGRATION_TYPES.find(
                (item) => item.value === migrationType
            ) || MIGRATION_TYPES[0],
        [migrationType]
    );

    const Icon = selectedMigration.icon;

    async function runSmokeTest() {
        if (loading) return;

        if (!target || typeof target !== "object") {
            setError(
                "Destination VM details are missing. Pass your targetVm object using the target prop."
            );
            return;
        }

        if (!target.ip && !target.host) {
            setError("Destination IP/host is missing.");
            return;
        }

        setLoading(true);
        setError("");
        setReport(null);

        const requestBody = {
            migration_type: migrationType,
            target,
            application: {
                pid: pid === "" ? undefined : pid,
                container_name:
                    containerName.trim() || undefined,
                name: containerName.trim() || undefined,
                port: port === "" ? undefined : port,
                check_http: Boolean(checkHttp),
            },
        };

        try {
            const response = await fetch(
                `${apiBasePath}/api/migration-smoke-test`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(requestBody),
                }
            );

            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(
                    data.error ||
                        data.message ||
                        `Smoke test request failed with HTTP ${response.status}.`
                );
            }

            setReport(data);

            if (typeof onComplete === "function") {
                onComplete(data);
            }
        } catch (err) {
            setError(
                err?.message ||
                    "Unable to execute smoke tests. Check backend connectivity."
            );
        } finally {
            setLoading(false);
        }
    }

    async function copyReport() {
        if (!report) return;

        try {
            await navigator.clipboard.writeText(
                JSON.stringify(report, null, 2)
            );
        } catch {
            setError(
                "Could not copy the report. Your browser may block clipboard access."
            );
        }
    }

    function downloadReport() {
        if (!report) return;

        const blob = new Blob(
            [JSON.stringify(report, null, 2)],
            { type: "application/json" }
        );

        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");

        anchor.href = url;
        anchor.download = `migration-smoke-test-${Date.now()}.json`;

        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();

        URL.revokeObjectURL(url);
    }

    const summary = report?.summary || {
        total: 0,
        passed: 0,
        failed: 0,
        skipped: 0,
        warnings: 0,
    };

    const results = Array.isArray(report?.results)
        ? report.results
        : [];

    const overallStatus = report?.status;
    const overallMeta = overallStatus
        ? STATUS_META[overallStatus] || STATUS_META.warning
        : null;

    return (
        <div style={styles.wrapper}>
            <div style={styles.panel}>
                {/* Header */}
                <div style={styles.header}>
                    <div style={{ minWidth: 0 }}>
                        <div style={styles.titleRow}>
                            <ShieldCheck size={23} color="#ea580c" />
                            <h2 style={styles.title}>
                                Migration Smoke Tests
                            </h2>
                        </div>

                        <p style={styles.subtitle}>
                            Verify destination connectivity, application
                            availability, container status and service health.
                        </p>
                    </div>

                    {overallMeta && (
                        <StatusBadge status={overallStatus} />
                    )}
                </div>

                {/* Migration type selector */}
                <div style={styles.section}>
                    <label style={styles.label}>
                        Migration type
                    </label>

                    <div style={styles.grid}>
                        {MIGRATION_TYPES.map((item) => {
                            const OptionIcon = item.icon;
                            const active =
                                migrationType === item.value;

                            return (
                                <button
                                    type="button"
                                    key={item.value}
                                    onClick={() => {
                                        setMigrationType(item.value);
                                        setReport(null);
                                        setError("");
                                    }}
                                    style={{
                                        ...styles.migrationOption,
                                        borderColor: active
                                            ? "#ea580c"
                                            : "#cbd5e1",
                                        background: active
                                            ? "#fff7ed"
                                            : "#fff",
                                        boxShadow: active
                                            ? "0 0 0 1px #ea580c"
                                            : "none",
                                    }}
                                >
                                    <OptionIcon
                                        size={19}
                                        color={
                                            active
                                                ? "#ea580c"
                                                : "#64748b"
                                        }
                                        style={{ flexShrink: 0 }}
                                    />

                                    <span style={{ minWidth: 0 }}>
                                        <span
                                            style={{
                                                display: "block",
                                                fontSize: 12,
                                                fontWeight: 700,
                                                lineHeight: 1.5,
                                            }}
                                        >
                                            {item.label}
                                        </span>

                                        <span
                                            style={{
                                                display: "block",
                                                color: "#64748b",
                                                fontSize: 11,
                                                lineHeight: 1.5,
                                                marginTop: 4,
                                            }}
                                        >
                                            {item.description}
                                        </span>
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Application details */}
                <div style={styles.section}>
                    <div style={styles.titleRow}>
                        <Network size={17} color="#64748b" />
                        <h3
                            style={{
                                margin: 0,
                                fontSize: 14,
                                fontWeight: 700,
                            }}
                        >
                            Application details
                        </h3>
                    </div>

                    <p
                        style={{
                            ...styles.subtitle,
                            marginBottom: 16,
                        }}
                    >
                        Destination:{" "}
                        <strong>
                            {target?.ip ||
                                target?.host ||
                                "Not provided"}
                        </strong>
                    </p>

                    <div style={styles.grid}>
                        {migrationType === "non_container" && (
                            <div>
                                <label style={styles.label}>
                                    Destination process PID
                                </label>
                                <input
                                    style={styles.input}
                                    type="number"
                                    min="1"
                                    value={pid}
                                    onChange={(event) =>
                                        setPid(event.target.value)
                                    }
                                    placeholder="e.g. 1234"
                                />
                            </div>
                        )}

                        {migrationType !== "non_container" && (
                            <div>
                                <label style={styles.label}>
                                    Container name
                                </label>
                                <input
                                    style={styles.input}
                                    value={containerName}
                                    onChange={(event) =>
                                        setContainerName(
                                            event.target.value
                                        )
                                    }
                                    placeholder="e.g. employee-app"
                                />
                            </div>
                        )}

                        <div>
                            <label style={styles.label}>
                                Application port
                            </label>
                            <input
                                style={styles.input}
                                type="number"
                                min="1"
                                max="65535"
                                value={port}
                                onChange={(event) =>
                                    setPort(event.target.value)
                                }
                                placeholder="e.g. 8080"
                            />
                        </div>
                    </div>

                    <label
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 9,
                            marginTop: 17,
                            color: "#475569",
                            fontSize: 12,
                            cursor: "pointer",
                        }}
                    >
                        <input
                            type="checkbox"
                            checked={checkHttp}
                            onChange={(event) =>
                                setCheckHttp(event.target.checked)
                            }
                        />
                        Check HTTP response on localhost at the application port
                    </label>

                    <p
                        style={{
                            ...styles.muted,
                            marginTop: 8,
                        }}
                    >
                        HTTP checks use the root path (/). For an application
                        with a different health endpoint, customize the backend
                        check accordingly.
                    </p>

                    <div
                        style={{
                            display: "flex",
                            flexWrap: "wrap",
                            gap: 9,
                            marginTop: 18,
                        }}
                    >
                        <button
                            type="button"
                            disabled={loading}
                            onClick={runSmokeTest}
                            style={{
                                ...styles.button,
                                ...styles.primaryButton,
                                ...(loading
                                    ? styles.disabledButton
                                    : {}),
                            }}
                        >
                            {loading ? (
                                <LoaderCircle
                                    size={16}
                                    className="migration-smoke-spin"
                                />
                            ) : report ? (
                                <RefreshCw size={16} />
                            ) : (
                                <Play size={16} />
                            )}

                            {loading
                                ? "Running smoke tests..."
                                : report
                                ? "Run Again"
                                : "Run Smoke Tests"}
                        </button>

                        {report && (
                            <>
                                <button
                                    type="button"
                                    style={styles.button}
                                    onClick={copyReport}
                                >
                                    <Copy size={15} />
                                    Copy JSON
                                </button>

                                <button
                                    type="button"
                                    style={styles.button}
                                    onClick={downloadReport}
                                >
                                    <Download size={15} />
                                    Download Report
                                </button>
                            </>
                        )}
                    </div>
                </div>

                {/* Error */}
                {error && (
                    <div
                        style={{
                            padding: "16px 22px 0",
                        }}
                    >
                        <div style={styles.errorBox}>
                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "flex-start",
                                    gap: 8,
                                }}
                            >
                                <AlertCircle
                                    size={18}
                                    style={{ flexShrink: 0 }}
                                />
                                <span>{error}</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Running state */}
                {loading && (
                    <div
                        style={{
                            ...styles.section,
                            textAlign: "center",
                        }}
                    >
                        <LoaderCircle
                            size={26}
                            color="#ea580c"
                            className="migration-smoke-spin"
                        />

                        <p
                            style={{
                                fontSize: 13,
                                fontWeight: 650,
                                margin: "12px 0 5px",
                            }}
                        >
                            Testing the destination application
                        </p>

                        <p style={styles.muted}>
                            Connecting over SSH and checking the selected
                            migration type. This may take several seconds.
                        </p>
                    </div>
                )}

                {/* Results */}
                {!loading && report && (
                    <div style={styles.section}>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "flex-start",
                                justifyContent: "space-between",
                                flexWrap: "wrap",
                                gap: 12,
                                marginBottom: 18,
                            }}
                        >
                            <div>
                                <div style={styles.titleRow}>
                                    <Icon
                                        size={19}
                                        color="#ea580c"
                                    />
                                    <h3
                                        style={{
                                            margin: 0,
                                            fontSize: 15,
                                            fontWeight: 750,
                                        }}
                                    >
                                        Smoke Test Report
                                    </h3>
                                </div>

                                <p style={styles.subtitle}>
                                    {selectedMigration.label}
                                    {" · "}
                                    {report.destination || target?.ip}
                                </p>
                            </div>

                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 6,
                                    color: "#64748b",
                                    fontSize: 12,
                                }}
                            >
                                <Clock3 size={14} />
                                {report.duration_ms ?? 0} ms
                            </div>
                        </div>

                        <div style={styles.summaryGrid}>
                            <SummaryCard
                                label="Total checks"
                                value={summary.total}
                            />
                            <SummaryCard
                                label="Passed"
                                value={summary.passed}
                                color="#15803d"
                            />
                            <SummaryCard
                                label="Failed"
                                value={summary.failed}
                                color="#b91c1c"
                            />
                            <SummaryCard
                                label="Warnings"
                                value={summary.warnings}
                                color="#a16207"
                            />
                            <SummaryCard
                                label="Skipped"
                                value={summary.skipped}
                                color="#64748b"
                            />
                        </div>

                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                gap: 10,
                                flexWrap: "wrap",
                                marginBottom: 12,
                            }}
                        >
                            <h4
                                style={{
                                    margin: 0,
                                    fontSize: 13,
                                    fontWeight: 750,
                                }}
                            >
                                Detailed results
                            </h4>

                            <button
                                type="button"
                                style={{
                                    ...styles.button,
                                    padding: "6px 9px",
                                    fontSize: 11,
                                }}
                                onClick={() =>
                                    setExpandedAll((previous) => !previous)
                                }
                            >
                                {expandedAll
                                    ? "Collapse all"
                                    : "Expand all"}
                            </button>
                        </div>

                        {results.length > 0 ? (
                            results.map((result, index) => (
                                <SmokeTestResultRow
                                    key={`${result.name}-${index}`}
                                    result={
                                        expandedAll
                                            ? {
                                                ...result,
                                                status: result.status,
                                            }
                                            : result
                                    }
                                    index={index}
                                />
                            ))
                        ) : (
                            <div style={styles.empty}>
                                No individual test results were returned.
                            </div>
                        )}

                        <div
                            style={{
                                display: "flex",
                                alignItems: "flex-start",
                                gap: 8,
                                background: "#f8fafc",
                                border: "1px solid #e2e8f0",
                                borderRadius: 9,
                                padding: 12,
                                marginTop: 14,
                            }}
                        >
                            <Terminal
                                size={16}
                                color="#64748b"
                                style={{ flexShrink: 0 }}
                            />

                            <div style={styles.muted}>
                                <strong>Interpretation:</strong>{" "}
                                A passed smoke test confirms the checks that
                                were executed. It does not guarantee every
                                application feature or business transaction
                                works correctly.
                            </div>
                        </div>
                    </div>
                )}

                {/* Empty state */}
                {!loading && !report && !error && (
                    <div style={styles.section}>
                        <div style={styles.empty}>
                            <ShieldCheck
                                size={30}
                                color="#94a3b8"
                                style={{ marginBottom: 10 }}
                            />

                            <div
                                style={{
                                    fontSize: 14,
                                    fontWeight: 700,
                                    color: "#334155",
                                }}
                            >
                                No smoke test report yet
                            </div>

                            <p
                                style={{
                                    ...styles.muted,
                                    margin: "7px auto 0",
                                    maxWidth: 430,
                                }}
                            >
                                Select the migration type, provide the
                                destination process or container details, and
                                click Run Smoke Tests to verify the migration.
                            </p>
                        </div>
                    </div>
                )}
            </div>

            <style>{`
                .migration-smoke-spin {
                    animation: migrationSmokeSpin 1s linear infinite;
                }

                @keyframes migrationSmokeSpin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }

                @media (prefers-reduced-motion: reduce) {
                    .migration-smoke-spin {
                        animation: none;
                    }
                }
            `}</style>
        </div>
    );
}
