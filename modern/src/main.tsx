import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpDown,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  CloudDownload,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Database,
  Ellipsis,
  FileJson,
  FileSpreadsheet,
  FolderOpen,
  History,
  Image as ImageIcon,
  Layers3,
  LayoutGrid,
  Link2,
  LoaderCircle,
  Monitor,
  Moon,
  Pencil,
  RefreshCw,
  Play,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Target,
  UsersRound,
  X,
  Zap,
} from "lucide-react";
import { api, ready } from "./bridge";
import { applyTheme, readTheme, type Theme } from "./theme";
import type {
  Assets,
  Card,
  CatalogResult,
  Draft,
  Filters,
  Options,
  Player,
  State,
} from "./types";
import "./styles.css";

const POSITIONS = ["DH", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"];
const MATCH: Record<string, string> = {
  verified: "일치",
  manual_selected: "직접 확인",
  ambiguous: "카드 선택",
  mismatch: "불일치",
  identity_unreadable: "이름 확인",
  unreadable_base: "능력치 확인",
};
const KINDS: Record<number, string> = {
  0: "라이브",
  1: "임팩트",
  2: "시그니처",
  3: "시즌",
  4: "골든글러브",
  5: "국가대표",
  6: "라이브 올스타",
};
function cardKind(card: Card) {
  return (
    card.impact_concept ||
    card.kind_label ||
    KINDS[card.kind ?? -1] ||
    "카드 미연결"
  );
}
function shortDate(path: string | null) {
  const match = path?.match(
    /(?:ldplayer|import)-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/,
  );
  return match
    ? `${match[1]}.${match[2]}.${match[3]} ${match[4]}:${match[5]}`
    : "수집 결과";
}
function Spinner() {
  return <LoaderCircle className="spin" size={17} aria-hidden="true" />;
}
function Grade({
  value,
  confirmed = true,
}: {
  value: string;
  confirmed?: boolean;
}) {
  const category = value.startsWith("S")
    ? "gold"
    : value.startsWith("A")
      ? "coral"
      : value.startsWith("B")
        ? "green"
        : value.startsWith("C")
          ? "blue"
          : "empty";
  return (
    <span
      className={`grade grade-${category}`}
      title={!confirmed ? "아직 확인되지 않은 값" : undefined}
    >
      {value || "−"}
      {!confirmed && value === "-" ? (
        <span className="sr-only"> 미확인</span>
      ) : null}
    </span>
  );
}

function Dialog({
  title,
  children,
  onClose,
  className = "",
  busy = false,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  className?: string;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current && !busy) {
          const rect = ref.current!.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            onClose();
        }
      }}
    >
      {children}
    </dialog>
  );
}

function App() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [state, setState] = useState<State | null>(null);
  const [assets, setAssets] = useState<Assets>({
    revision: -1,
    portraits: {},
    skills: {},
  });
  const [options, setOptions] = useState<Options | null>(null);
  const [view, setView] = useState<"roster" | "logs">("roster");
  const [selected, setSelected] = useState("DH");
  const [query, setQuery] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [sort, setSort] = useState<"position" | "order">("position");
  const [count, setCount] = useState(9);
  const [pending, setPending] = useState(false);
  const [modal, setModal] = useState<{
    kind: "edit" | "picker" | "settings";
    slot?: string;
  } | null>(null);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
    null,
  );
  const [connectionError, setConnectionError] = useState("");
  const revision = useRef(-1);
  const searchRef = useRef<HTMLInputElement>(null);
  const accept = useCallback((next: State | null) => {
    if (next && next.revision >= revision.current) {
      revision.current = next.revision;
      setState(next);
    }
  }, []);
  const notify = useCallback(
    (text: string, error = false) => setToast({ text, error }),
    [],
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme, media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [theme]);
  useEffect(() => {
    if (state?.theme) setTheme(state.theme);
  }, [state?.theme]);
  async function chooseTheme(value: Theme) {
    const previous = theme;
    setTheme(value);
    try {
      accept(await api<State>("set_theme", value));
    } catch (error) {
      setTheme(previous);
      notify((error as Error).message, true);
    }
  }
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<State & { unchanged?: boolean }>(
          "get_state",
          revision.current,
        );
        if (!stopped) {
          if (!next.unchanged) accept(next);
          setConnectionError("");
        }
      } catch (error) {
        if (!stopped) setConnectionError(String((error as Error).message));
      }
      if (!stopped) timer = setTimeout(poll, 650);
    }
    ready().then(() => {
      if (!stopped) {
        api<Options>("get_options")
          .then(setOptions)
          .catch((error) => notify(error.message, true));
        poll();
      }
    });
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [accept, notify]);
  useEffect(() => {
    if (state && state.asset_revision !== assets.revision) {
      let active = true;
      api<Assets>("get_assets")
        .then((next) => {
          if (active) setAssets(next);
        })
        .catch(() => {});
      return () => {
        active = false;
      };
    }
  }, [state?.asset_revision, assets.revision]);
  useEffect(() => {
    if (state?.database)
      api<Options>("get_options")
        .then(setOptions)
        .catch((error) => notify(error.message, true));
  }, [state?.database, state?.catalog.version, notify]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), toast.error ? 11000 : 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === "f" && !modal) {
        event.preventDefault();
        setView("roster");
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [modal]);
  useEffect(() => {
    if (state && !state.records.some((r) => r.slot === selected))
      setSelected(state.records[0]?.slot || "DH");
  }, [state?.records, selected]);
  async function perform(name: string, ...args: unknown[]) {
    setPending(true);
    try {
      const result = await api<State | null>(name, ...args);
      accept(result);
      if (result?.last_export && name === "export_dialog")
        notify("파일을 저장했습니다. 웹 관리기의 시트 가져오기로 불러오세요.");
      return result;
    } catch (error) {
      notify((error as Error).message, true);
      return null;
    } finally {
      setPending(false);
    }
  }
  async function openModal(value: typeof modal) {
    try {
      await api("set_editing", !!value);
      setModal(value);
    } catch (error) {
      notify((error as Error).message, true);
    }
  }
  function closeModal() {
    setModal(null);
    api("set_editing", false).catch(() => {});
  }
  const busy = !!state?.busy || pending;
  const rows = (state?.records || [])
    .filter(
      (r) =>
        (!reviewOnly || r.review_count > 0) &&
        `${r.name} ${cardKind(r.card)} ${r.slot}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "order"
        ? (a.batting_order ?? 99) - (b.batting_order ?? 99)
        : POSITIONS.indexOf(a.slot) - POSITIONS.indexOf(b.slot),
    );
  const player = state?.records.find((r) => r.slot === selected);
  const modalPlayer = state?.records.find((r) => r.slot === modal?.slot);
  const metrics = state?.metrics || {
    players: 0,
    potentials: 0,
    skills: 0,
    review: 0,
  };

  if (!state)
    return (
      <div className="boot">
        <div className="brand-mark">
          <Layers3 />
        </div>
        <h1>LINEUP</h1>
        <p>로컬 엔진에 연결하고 있어요.</p>
        <Spinner />
        <p className="muted">{connectionError}</p>
      </div>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Layers3 size={24} />
          </div>
          <div>
            <strong>
              LINEUP<span className="brand-dot">.</span>
            </strong>
            <span>YOUR DECK COMPANION</span>
          </div>
        </div>
        <p className="nav-caption">WORKSPACE</p>
        <nav aria-label="주 메뉴">
          <button
            className={`nav-item ${view === "roster" ? "active" : ""}`}
            onClick={() => setView("roster")}
          >
            <LayoutGrid size={19} />내 라인업
            <span className="nav-count">{state.records.length}</span>
          </button>
          <button
            className={`nav-item ${view === "logs" ? "active" : ""}`}
            onClick={() => setView("logs")}
          >
            <History size={19} />
            작업 기록{state.busy && <span className="live-dot" />}
          </button>
          <button
            className="nav-item"
            disabled={busy}
            onClick={() => openModal({ kind: "settings" })}
          >
            <Settings2 size={19} />
            카드 데이터 설정
          </button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="appearance">
          <span>화면 테마</span>
          <div role="group" aria-label="화면 테마">
            {(
              [
                ["system", "시스템", Monitor],
                ["light", "라이트", Sun],
                ["dark", "다크", Moon],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                className={theme === value ? "selected" : ""}
                aria-pressed={theme === value}
                onClick={() => chooseTheme(value)}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="shortcut-card">
          <div className="shortcut-heading">
            <Zap size={16} />
            <span>게임에서 바로 읽기</span>
          </div>
          <div className="shortcut">
            <div>
              <strong>잠재력</strong>
              <span>풀스윙 · 클러치 · 각잠</span>
            </div>
            <kbd>F6</kbd>
          </div>
          <div className="shortcut">
            <div>
              <strong>스킬</strong>
              <span>스킬 이름과 레벨</span>
            </div>
            <kbd>F7</kbd>
          </div>
          <p>
            한눈에 보기에서 주전 9명과
            <br />열 제목을 맞춘 뒤 눌러 주세요.
          </p>
        </div>
        <button
          className="sidebar-help"
          onClick={() =>
            notify(
              "게임 라인업에서 수집 → 한눈에 보기에서 F6/F7 → 선수 확인 → 엑셀 내보내기 순서로 진행하세요.",
            )
          }
        >
          <BookOpen size={16} />
          사용 순서 보기
          <ArrowUpRight size={15} />
        </button>
        <div className="engine-status">
          <span className={`live-dot ${connectionError ? "offline" : ""}`} />
          <span>
            {connectionError ? "엔진 연결 확인 필요" : "로컬 엔진 연결됨"}
          </span>
          <small>v{state.version}</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="page-header">
          <div>
            <div className="eyebrow">
              {view === "roster" ? "ROSTER OVERVIEW" : "ACTIVITY LOG"}
            </div>
            <h1>
              {view === "roster" ? "내 라인업" : "작업 기록"}
              <span className="page-badge">LDPlayer</span>
            </h1>
            <p>
              {view === "roster"
                ? "카드를 모으고, 확인하고, 내 덱으로."
                : "수집과 저장 과정에서 확인한 내용을 모아봤어요."}
            </p>
          </div>
          <div className="header-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => perform("choose_result")}
            >
              <FolderOpen size={17} />
              결과 열기
            </button>
            <details className="more-menu">
              <summary className="icon-button" aria-label="기타 저장 메뉴">
                <Ellipsis size={21} />
              </summary>
              <div className="menu-content">
                <button
                  disabled={busy || !state.records.length}
                  onClick={() => {
                    document
                      .querySelector(".more-menu")
                      ?.removeAttribute("open");
                    perform("save");
                  }}
                >
                  <Check size={16} />
                  현재 결과 저장
                </button>
                <button
                  disabled={busy || !state.records.length}
                  onClick={() => {
                    document
                      .querySelector(".more-menu")
                      ?.removeAttribute("open");
                    perform("export_dialog", "json");
                  }}
                >
                  <FileJson size={16} />
                  JSON 내보내기
                </button>
                <button
                  disabled={busy || !state.records.length}
                  onClick={() => {
                    document
                      .querySelector(".more-menu")
                      ?.removeAttribute("open");
                    perform("export_dialog", "csv");
                  }}
                >
                  <FileSpreadsheet size={16} />
                  전체 항목 CSV
                </button>
                <hr />
                <button
                  onClick={() =>
                    api("open_folder").catch((error) =>
                      notify(error.message, true),
                    )
                  }
                >
                  <FolderOpen size={16} />
                  결과 폴더 열기
                </button>
              </div>
            </details>
            <button
              className="button primary"
              disabled={busy || !state.records.length}
              onClick={() => perform("export_dialog", "xlsx")}
            >
              <ArrowDownToLine size={18} />
              엑셀 내보내기
            </button>
          </div>
        </header>
        {state.preview && (
          <div className="preview-note">
            <ShieldCheck size={15} />
            미리보기 · 수집 결과 복사본을 사용합니다. 게임 수집과 단축키는 꺼져
            있어요.
          </div>
        )}
        {connectionError && (
          <div className="error-banner" role="alert">
            {connectionError}
          </div>
        )}

        {view === "roster" ? (
          <>
            <section className="metrics" aria-label="수집 진행 현황">
              {(
                [
                  [
                    "주전 라인업",
                    metrics.players,
                    9,
                    UsersRound,
                    "선수 카드",
                    "mint",
                  ],
                  [
                    "잠재력",
                    metrics.potentials,
                    27,
                    Sparkles,
                    "풀스윙 · 클러치 · 각잠",
                    "violet",
                  ],
                  [
                    "스킬",
                    metrics.skills,
                    27,
                    Target,
                    "스킬 이름과 레벨",
                    "blue",
                  ],
                  [
                    "확인 필요",
                    metrics.review,
                    null,
                    ClipboardList,
                    metrics.review
                      ? "선수 정보를 확인해 주세요"
                      : state.records.length
                        ? "모두 확인했어요"
                        : "수집 후 확인할 수 있어요",
                    "amber",
                  ],
                ] as const
              ).map(([label, value, total, Icon, hint, color]) => (
                <div className="metric-card" key={label}>
                  <div className={`metric-icon ${color}`}>
                    <Icon size={20} />
                  </div>
                  <div className="metric-content">
                    <span>{label}</span>
                    <div className="metric-value">
                      {value}
                      {total ? <small>/ {total}</small> : <small>명</small>}
                    </div>
                    <p>{hint}</p>
                  </div>
                  {total && value === total && (
                    <span className="metric-check">
                      <Check size={13} />
                    </span>
                  )}
                </div>
              ))}
            </section>
            <section
              className={`collection-bar ${state.busy ? "working" : ""}`}
              aria-label="선수 수집"
            >
              <div className="collection-icon">
                {state.busy ? <Spinner /> : <Layers3 size={22} />}
              </div>
              <div className="collection-copy">
                <strong>
                  {state.busy === "scan"
                    ? "선수 카드를 수집하고 있어요"
                    : state.busy === "potentials"
                      ? "잠재력을 읽고 있어요"
                      : state.busy === "skills"
                        ? "스킬을 읽고 있어요"
                        : "게임 속 라인업을 가져오세요"}
                </strong>
                <span>
                  {state.busy
                    ? state.status
                    : "타자 라인업 화면에서 시작하면 DH부터 순서대로 수집해요."}
                </span>
              </div>
              <div className="collection-actions">
                <select
                  aria-label="수집 범위"
                  value={count}
                  disabled={busy}
                  onChange={(event) => setCount(Number(event.target.value))}
                >
                  <option value={9}>주전 9명</option>
                  <option value={1}>DH 1명 테스트</option>
                </select>
                {state.busy === "scan" ? (
                  <button
                    className="button stop"
                    onClick={() => perform("stop_scan")}
                  >
                    <Square size={13} fill="currentColor" />
                    중지<kbd>F8</kbd>
                  </button>
                ) : (
                  <button
                    className="button collect"
                    disabled={busy || state.preview}
                    onClick={() => perform("start_scan", count)}
                  >
                    <Play size={14} fill="currentColor" />
                    수집 시작
                  </button>
                )}
              </div>
            </section>
            <section className="roster-card">
              <div className="table-toolbar">
                <div className="table-title">
                  <h2>주전 선수</h2>
                  <span>{state.records.length}</span>
                </div>
                <div className="table-tools">
                  <label className="search-box">
                    <Search size={16} />
                    <input
                      ref={searchRef}
                      aria-label="선수 검색"
                      placeholder="선수 이름 검색"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                    />
                    {query && (
                      <button
                        aria-label="검색 지우기"
                        className="clear-search"
                        onClick={() => setQuery("")}
                      >
                        <X size={13} />
                      </button>
                    )}
                    <kbd>Ctrl F</kbd>
                  </label>
                  <button
                    className={`filter-button ${reviewOnly ? "selected" : ""}`}
                    aria-pressed={reviewOnly}
                    onClick={() => setReviewOnly((value) => !value)}
                  >
                    <CircleAlert size={15} />
                    확인 필요
                    {metrics.review > 0 && <span>{metrics.review}</span>}
                  </button>
                  <button
                    className="icon-button sort-button"
                    aria-label={
                      sort === "position" ? "타순으로 정렬" : "포지션으로 정렬"
                    }
                    title={
                      sort === "position" ? "타순으로 정렬" : "포지션으로 정렬"
                    }
                    onClick={() =>
                      setSort(sort === "position" ? "order" : "position")
                    }
                  >
                    <ArrowUpDown size={17} />
                  </button>
                </div>
              </div>
              <div className="table-scroll">
                <table className="roster-table">
                  <thead>
                    <tr>
                      <th>포지션</th>
                      <th>타순</th>
                      <th className="player-heading">선수</th>
                      <th>강화 · 각성</th>
                      <th>발사각</th>
                      <th>풀스윙</th>
                      <th>클러치</th>
                      <th>각잠</th>
                      <th className="skill-heading">스킬 · 레벨</th>
                      <th>카드 연결</th>
                      <th>
                        <span className="sr-only">선수 작업</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((record) => (
                      <tr
                        key={record.slot}
                        className={`${selected === record.slot ? "is-selected" : ""} ${record.review_count ? "needs-review" : ""}`}
                        tabIndex={0}
                        aria-selected={selected === record.slot}
                        onClick={() => setSelected(record.slot)}
                        onDoubleClick={() =>
                          !busy &&
                          openModal({ kind: "edit", slot: record.slot })
                        }
                        onKeyDown={(event) => {
                          if (
                            event.target === event.currentTarget &&
                            event.key === "Enter" &&
                            !busy
                          )
                            openModal({ kind: "edit", slot: record.slot });
                        }}
                      >
                        <td>
                          <span
                            className={`position position-${record.slot === "DH" ? "dh" : ["LF", "CF", "RF"].includes(record.slot) ? "outfield" : "infield"}`}
                          >
                            {record.slot}
                          </span>
                        </td>
                        <td>
                          <span className="order-number">
                            {record.batting_order || "—"}
                          </span>
                        </td>
                        <td>
                          <div className="player-cell">
                            {assets.portraits[record.slot] ? (
                              <img
                                className="player-avatar"
                                src={assets.portraits[record.slot]}
                                alt=""
                              />
                            ) : (
                              <div className="player-avatar initials">
                                {record.name.slice(0, 1)}
                              </div>
                            )}
                            <div>
                              <strong>
                                {record.name}
                                {record.fa && (
                                  <span className="fa-label">FA</span>
                                )}
                              </strong>
                              <span>{cardKind(record.card)}</span>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span
                            className={`stage ${record.enhance.includes("각성") ? "awakened" : ""}`}
                          >
                            {record.enhance || "—"}
                          </span>
                        </td>
                        <td className="angle">
                          {record.launch_angle !== null ? (
                            <>
                              {record.launch_angle}
                              <small>°</small>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                        {(["pot1", "pot2", "pot3"] as const).map((key) => (
                          <td key={key}>
                            <Grade
                              value={record[key]}
                              confirmed={record.potentials_confirmed[key]}
                            />
                          </td>
                        ))}
                        <td>
                          <div className="skill-chips">
                            {[0, 1, 2].map((index) => {
                              const skill = record.skills[index];
                              return skill?.name ? (
                                <span
                                  className="skill-chip"
                                  key={index}
                                  title={`${skill.name} · 레벨 ${skill.lv ?? "미확인"}`}
                                >
                                  {assets.skills[skill.name] && (
                                    <img
                                      src={assets.skills[skill.name]}
                                      alt=""
                                    />
                                  )}
                                  <span>{skill.name}</span>
                                  <b>{skill.lv ?? "?"}</b>
                                </span>
                              ) : (
                                <span
                                  className="skill-chip missing"
                                  key={index}
                                >
                                  미수집
                                </span>
                              );
                            })}
                          </div>
                        </td>
                        <td>
                          <button
                            className={`match-status ${["verified", "manual_selected"].includes(record.match_status) ? "matched" : "unmatched"}`}
                            disabled={busy}
                            onClick={(event) => {
                              event.stopPropagation();
                              openModal({ kind: "picker", slot: record.slot });
                            }}
                          >
                            {["verified", "manual_selected"].includes(
                              record.match_status,
                            ) ? (
                              <CheckCheck size={14} />
                            ) : (
                              <CircleAlert size={14} />
                            )}
                            {MATCH[record.match_status] || "미연결"}
                          </button>
                        </td>
                        <td>
                          <button
                            className="icon-button edit-button"
                            aria-label={`${record.name} 수정`}
                            title="선수 수정"
                            disabled={busy}
                            onClick={(event) => {
                              event.stopPropagation();
                              openModal({ kind: "edit", slot: record.slot });
                            }}
                          >
                            <Pencil size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && (
                  <div className="empty-state">
                    <div className="empty-icon">
                      {state.records.length ? (
                        <Search size={28} />
                      ) : (
                        <Layers3 size={30} />
                      )}
                    </div>
                    <h3>
                      {state.records.length
                        ? "조건에 맞는 선수가 없어요"
                        : "첫 라인업을 가져와 볼까요?"}
                    </h3>
                    <p>
                      {state.records.length
                        ? "검색어를 바꾸거나 확인 필요 필터를 해제해 보세요."
                        : "LDPlayer에서 수집을 시작하거나 저장해 둔 결과를 열어 주세요."}
                    </p>
                    {!state.records.length && (
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() => perform("choose_result")}
                      >
                        <FolderOpen size={16} />
                        저장된 결과 열기
                      </button>
                    )}
                  </div>
                )}
              </div>
              <div className="table-footer">
                <span>
                  {rows.length}명 표시 <i />{" "}
                  {sort === "position" ? "포지션 순서" : "실제 타순"}
                  <i />
                  선수를 더블클릭하면 수정할 수 있어요.
                </span>
                <span className="preserved">
                  <ShieldCheck size={14} />
                  원본 보존
                </span>
              </div>
            </section>
            <footer className="workspace-footer">
              <span className={`status-line ${state.busy ? "active" : ""}`}>
                {state.busy ? <Spinner /> : <span className="live-dot" />}
                {state.status}
              </span>
              {state.current && (
                <button
                  title={state.current}
                  onClick={() =>
                    api("open_folder").catch((error) =>
                      notify(error.message, true),
                    )
                  }
                >
                  <FolderOpen size={14} />
                  {shortDate(state.original || state.current)}
                  <ArrowUpRight size={13} />
                </button>
              )}
            </footer>
          </>
        ) : (
          <section className="logs-card">
            <div className="section-heading">
              <div>
                <h2>최근 작업</h2>
                <p>최대 200개의 기록을 표시합니다.</p>
              </div>
              <button
                className="button secondary"
                onClick={() =>
                  api("open_folder").catch((error) =>
                    notify(error.message, true),
                  )
                }
              >
                <FolderOpen size={16} />
                결과 폴더
              </button>
            </div>
            {state.logs.length ? (
              <div className="log-list">
                {[...state.logs].reverse().map((log) => (
                  <div className={`log-entry ${log.level}`} key={log.id}>
                    <span className="log-symbol">
                      {log.level === "error" || log.level === "warning" ? (
                        <CircleAlert size={17} />
                      ) : (
                        <Activity size={17} />
                      )}
                    </span>
                    <time>{log.time}</time>
                    <p>{log.message}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <History size={32} />
                <h3>아직 작업 기록이 없어요</h3>
                <p>수집과 저장을 시작하면 여기에 표시됩니다.</p>
              </div>
            )}
          </section>
        )}
      </main>
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <CircleAlert size={20} /> : <Check size={20} />}
          <p>{toast.text}</p>
          <button aria-label="알림 닫기" onClick={() => setToast(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      {modal?.kind === "settings" && (
        <Dialog
          title="공통 데이터 관리"
          className="data-settings-dialog"
          onClose={closeModal}
          busy={pending}
        >
          <div className="dialog-header">
            <div>
              <span className="eyebrow">DATA SOURCE</span>
              <h2>공통 데이터 관리</h2>
            </div>
            <button
              className="icon-button"
              aria-label="설정 닫기"
              onClick={closeModal}
            >
              <X size={20} />
            </button>
          </div>
          <div className="settings-body">
            <div className="data-source-icon">
              <CloudDownload size={28} />
            </div>
            <h3>{state.database_count.toLocaleString()}장의 타자 카드</h3>
            <p>
              카드와 스킬의 공통 자료를 내려받아 이 기기에 보관합니다. 연결이
              끊겨도 마지막 정상 데이터를 사용할 수 있어요.
            </p>
            <div className="catalog-info">
              <div>
                <span>사용 중인 카드 자료</span>
                <strong>
                  {state.catalog.source === "server"
                    ? "서버 공통 데이터"
                    : state.catalog.source === "manual"
                      ? "직접 선택한 JSON"
                      : "앱에 포함된 기본 자료"}
                </strong>
              </div>
              <div>
                <span>스킬 자료</span>
                <strong>
                  {state.catalog.counts
                    ? `${state.catalog.counts.skills}개 · 타자 ${state.catalog.counts.batter_skills} / 투수 ${state.catalog.counts.pitcher_skills}`
                    : "기본 판독 자료"}
                </strong>
              </div>
              <div>
                <span>데이터 버전</span>
                <strong>{state.catalog.version || "서버 연결 후 표시"}</strong>
              </div>
            </div>
            {state.catalog.error && (
              <div className="error-banner data-error" role="status">
                <CircleAlert size={16} />
                <span>
                  서버에 연결하지 못해 현재 자료를 유지하고 있어요. 배포 또는
                  인터넷 연결을 확인한 뒤 다시 시도해 주세요.
                </span>
              </div>
            )}
            {state.catalog.pending && (
              <div className="info-note data-pending">
                <Check size={17} />
                <span>
                  다운로드를 마쳤습니다. 이 창을 닫으면 새 자료를 적용합니다.
                </span>
              </div>
            )}
            <button
              className="button primary"
              disabled={pending || state.catalog.syncing}
              onClick={() => perform("sync_catalog")}
            >
              <RefreshCw
                size={17}
                className={state.catalog.syncing ? "spin" : ""}
              />
              {state.catalog.syncing
                ? "새 데이터 확인 중"
                : "공통 데이터 업데이트"}
            </button>
            {state.catalog.source === "manual" && state.catalog.version && (
              <button
                className="button secondary server-source-button"
                disabled={pending}
                onClick={() => perform("use_server_catalog")}
              >
                서버 카드 자료로 전환
              </button>
            )}
            <details className="extra-fields manual-data">
              <summary>
                수동으로 카드 JSON 선택
                <ChevronDown size={15} />
              </summary>
              <span className="path-value">{state.database}</span>
              <button
                className="button secondary"
                disabled={pending}
                onClick={() => perform("choose_database")}
              >
                <FolderOpen size={17} />
                카드 JSON 선택
              </button>
            </details>
            <div className="info-note">
              <ShieldCheck size={17} />
              <span>
                서버에는 공통 카드·스킬 자료만 있어요.
                <br />
                개인 라인업과 캡처 이미지는 올리지 않습니다.
              </span>
            </div>
          </div>
          <div className="dialog-footer">
            <button className="button primary" onClick={closeModal}>
              확인
            </button>
          </div>
        </Dialog>
      )}
      {modal?.kind === "edit" && modalPlayer && options && (
        <PlayerEditor
          player={modalPlayer}
          version={state.records_version}
          options={options}
          assets={assets}
          onClose={closeModal}
          onState={accept}
          notify={notify}
        />
      )}
      {modal?.kind === "picker" && modalPlayer && options && (
        <CardPicker
          player={modalPlayer}
          version={state.records_version}
          options={options}
          onClose={closeModal}
          onState={accept}
          onSelected={closeModal}
        />
      )}
    </div>
  );
}

function PlayerEditor({
  player,
  version,
  options,
  assets,
  onClose,
  onState,
  notify,
}: {
  player: Player;
  version: number;
  options: Options;
  assets: Assets;
  onClose: () => void;
  onState: (state: State) => void;
  notify: (text: string, error?: boolean) => void;
}) {
  const [tab, setTab] = useState<"info" | "stats" | "issues">("info");
  const [form, setForm] = useState<Draft>(() => ({
    launch_angle: player.launch_angle?.toString() || "",
    enhance: player.enhance,
    batting_order: player.batting_order?.toString() || "",
    fa: player.fa,
    pot1: player.pot1,
    pot2: player.pot2,
    pot3: player.pot3,
    hand: player.hand,
    white_zone: player.white_zone,
    cold_zone: player.cold_zone,
    skills: [0, 1, 2].map((i) => ({
      name: player.skills[i]?.name || "",
      lv: player.skills[i]?.lv?.toString() || "",
    })),
    stats: Object.fromEntries(
      Object.entries(player.stats).map(([row, values]) => [
        row,
        Object.fromEntries(
          Object.entries(values).map(([key, value]) => [
            key,
            value?.toString() ?? "",
          ]),
        ),
      ]),
    ),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [picker, setPicker] = useState(false);
  const [linked, setLinked] = useState(player);
  const recordVersion = useRef(version);
  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      const state = await api<State>(
        "update_record",
        player.slot,
        form,
        recordVersion.current,
      );
      onState(state);
      notify("선수 정보를 저장했습니다.");
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <Dialog
        title={`${player.name} 선수 수정`}
        className="drawer"
        onClose={onClose}
        busy={saving}
      >
        <form className="editor-form" onSubmit={save}>
          <div className="dialog-header">
            <div>
              <span className="eyebrow">PLAYER DETAILS</span>
              <h2>선수 정보 수정</h2>
            </div>
            <button
              type="button"
              className="icon-button"
              aria-label="선수 수정 닫기"
              disabled={saving}
              onClick={onClose}
            >
              <X size={20} />
            </button>
          </div>
          <div className="editor-player">
            <div className="editor-portrait">
              {assets.portraits[player.slot] ? (
                <img
                  src={assets.portraits[player.slot]}
                  alt={`${player.name} 카드`}
                />
              ) : (
                <UsersRound size={40} />
              )}
            </div>
            <div className="editor-identity">
              <div>
                <span className="position">{player.slot}</span>
                <span className="card-kind">{cardKind(linked.card)}</span>
              </div>
              <h3>{linked.name}</h3>
              <p>
                {linked.card.stars ? `${linked.card.stars}성` : "성급 미확인"}
                {linked.card.season && linked.card.season < 2101
                  ? ` · ${linked.card.season}`
                  : ""}
              </p>
              <button
                className="text-button"
                type="button"
                disabled={saving}
                onClick={() => setPicker(true)}
              >
                <Link2 size={14} />
                카드 다시 연결
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
          <div className="tabs" role="tablist" aria-label="선수 수정 항목">
            {(
              [
                ["info", "선수 · 잠재력 · 스킬"],
                ["stats", "세부 능력치"],
                ["issues", `확인 사항 ${player.issues.length}`],
              ] as const
            ).map(([value, label]) => (
              <button
                id={`tab-${value}`}
                key={value}
                role="tab"
                type="button"
                aria-selected={tab === value}
                aria-controls="editor-panel"
                onClick={() => setTab(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            className="editor-scroll"
            id="editor-panel"
            role="tabpanel"
            aria-labelledby={`tab-${tab}`}
          >
            {error && (
              <div className="error-banner" role="alert">
                <CircleAlert size={17} />
                <span>{error}</span>
              </div>
            )}
            <fieldset disabled={saving}>
              {tab === "info" && (
                <>
                  <section className="form-section">
                    <h4>
                      기본 정보<span>게임에서 확인한 값을 입력해 주세요.</span>
                    </h4>
                    <div className="field-grid">
                      <label className="field">
                        발사각
                        <div className="input-unit">
                          <input
                            type="number"
                            value={form.launch_angle}
                            onChange={(e) =>
                              change("launch_angle", e.target.value)
                            }
                          />
                          <span>°</span>
                        </div>
                      </label>
                      <label className="field">
                        강화 · 각성 단계
                        <input
                          placeholder="예: 10강, 3각성"
                          value={form.enhance}
                          onChange={(e) => change("enhance", e.target.value)}
                        />
                      </label>
                      <label className="field">
                        실제 타순
                        <select
                          value={form.batting_order}
                          onChange={(e) =>
                            change("batting_order", e.target.value)
                          }
                        >
                          <option value="">미확인</option>
                          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
                            <option key={n} value={n}>
                              {n}번
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field">
                        FA 표시
                        <select
                          value={form.fa ? "fa" : "normal"}
                          onChange={(e) =>
                            change("fa", e.target.value === "fa")
                          }
                        >
                          <option value="normal">일반</option>
                          <option value="fa">FA</option>
                        </select>
                      </label>
                    </div>
                  </section>
                  <section className="form-section">
                    <h4>
                      잠재력<span>없음 또는 미인식은 −로 표시합니다.</span>
                    </h4>
                    <div className="potential-fields">
                      {(
                        [
                          ["pot1", "풀스윙"],
                          ["pot2", "클러치"],
                          ["pot3", "각성 잠재력"],
                        ] as const
                      ).map(([key, label]) => (
                        <label className="field" key={key}>
                          {label}
                          <div className="potential-select">
                            <Grade value={form[key]} />
                            <select
                              aria-label={label}
                              value={form[key]}
                              onChange={(e) => change(key, e.target.value)}
                            >
                              <option value="-">−</option>
                              {(key === "pot3"
                                ? options.awake_grades
                                : options.grades
                              ).map((value) => (
                                <option key={value}>{value}</option>
                              ))}
                            </select>
                            <ChevronDown
                              className="potential-chevron"
                              size={14}
                              aria-hidden="true"
                            />
                          </div>
                        </label>
                      ))}
                    </div>
                  </section>
                  <section className="form-section">
                    <h4>
                      스킬
                      <span>목록의 스킬 이름과 숫자 레벨을 입력하세요.</span>
                    </h4>
                    <datalist id="skill-options">
                      {options.skills.map((name) => (
                        <option value={name} key={name} />
                      ))}
                    </datalist>
                    {form.skills.map((skill, index) => (
                      <div className="skill-form-row" key={index}>
                        <span className="skill-slot">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <label className="field">
                          <span className="sr-only">스킬 {index + 1} 이름</span>
                          <input
                            list="skill-options"
                            placeholder="스킬 이름 선택 또는 검색"
                            value={skill.name}
                            onChange={(e) =>
                              change(
                                "skills",
                                form.skills.map((s, i) =>
                                  i === index
                                    ? { ...s, name: e.target.value }
                                    : s,
                                ),
                              )
                            }
                          />
                        </label>
                        <span className="level-label">LV.</span>
                        <label className="field skill-level">
                          <span className="sr-only">스킬 {index + 1} 레벨</span>
                          <input
                            type="number"
                            min={1}
                            max={99}
                            placeholder="−"
                            value={skill.lv}
                            onChange={(e) =>
                              change(
                                "skills",
                                form.skills.map((s, i) =>
                                  i === index
                                    ? { ...s, lv: e.target.value }
                                    : s,
                                ),
                              )
                            }
                          />
                        </label>
                      </div>
                    ))}
                  </section>
                  <details className="extra-fields">
                    <summary>
                      추가 시트 정보
                      <ChevronDown size={15} />
                    </summary>
                    <div className="field-grid">
                      <label className="field">
                        타격 방향
                        <input
                          value={form.hand}
                          onChange={(e) => change("hand", e.target.value)}
                          placeholder="예: 좌"
                        />
                      </label>
                      <label className="field">
                        흰존
                        <input
                          value={form.white_zone}
                          onChange={(e) => change("white_zone", e.target.value)}
                        />
                      </label>
                      <label className="field">
                        콜존
                        <input
                          value={form.cold_zone}
                          onChange={(e) => change("cold_zone", e.target.value)}
                        />
                      </label>
                    </div>
                  </details>
                </>
              )}
              {tab === "stats" && (
                <>
                  <div className="info-note">
                    <ShieldCheck size={17} />
                    <span>
                      게임 화면의 행별 숫자를 그대로 입력하세요.
                      <br />
                      기본 능력치는 연결된 카드 데이터와 다시 대조합니다.
                    </span>
                  </div>
                  <div className="stat-editor-scroll">
                    <table className="stat-editor">
                      <thead>
                        <tr>
                          <th>항목</th>
                          {options.stats.map((stat) => (
                            <th key={stat}>{stat}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(form.stats).map(([row, values]) => (
                          <tr
                            key={row}
                            className={
                              row === "기본" || row === "종합" ? "emphasis" : ""
                            }
                          >
                            <th>{row}</th>
                            {options.stats.map((stat) => (
                              <td key={stat}>
                                <input
                                  type="number"
                                  aria-label={`${row} ${stat}`}
                                  value={values[stat] ?? ""}
                                  onChange={(e) =>
                                    change("stats", {
                                      ...form.stats,
                                      [row]: {
                                        ...values,
                                        [stat]: e.target.value,
                                      },
                                    })
                                  }
                                />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {tab === "issues" && (
                <div className="review-panel">
                  {player.issues.length ? (
                    <>
                      <h4>이 선수에게 확인할 내용</h4>
                      {player.issues.map((issue, index) => (
                        <div className="review-item" key={index}>
                          <CircleAlert size={17} />
                          <span>{issue}</span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <div className="review-complete">
                      <div>
                        <CheckCheck size={32} />
                      </div>
                      <h3>모두 확인했어요</h3>
                      <p>현재 수집 결과에서 추가 확인 항목이 없습니다.</p>
                    </div>
                  )}
                  <p className="muted">카드 대조: {linked.match_message}</p>
                </div>
              )}
            </fieldset>
          </div>
          <div className="dialog-footer editor-footer">
            <button
              type="button"
              className="text-button"
              onClick={() =>
                api(
                  "open_evidence",
                  player.slot,
                  tab === "stats" ? "stats" : "overview",
                ).catch((error) => notify(error.message, true))
              }
            >
              <ImageIcon size={16} />
              원본 이미지
            </button>
            <div>
              <button
                type="button"
                className="button secondary"
                disabled={saving}
                onClick={onClose}
              >
                취소
              </button>
              <button
                type="submit"
                className="button primary"
                disabled={saving}
              >
                {saving ? <Spinner /> : <Check size={17} />}검증 후 저장
              </button>
            </div>
          </div>
        </form>
      </Dialog>
      {picker && (
        <CardPicker
          player={linked}
          version={recordVersion.current}
          options={options}
          onClose={() => setPicker(false)}
          onState={(data) => {
            onState(data);
            recordVersion.current = data.records_version;
            setLinked(data.records.find((r) => r.slot === player.slot)!);
          }}
          onSelected={() => setPicker(false)}
        />
      )}
    </>
  );
}

function CardPicker({
  player,
  version,
  options,
  onClose,
  onState,
  onSelected,
}: {
  player: Player;
  version: number;
  options: Options;
  onClose: () => void;
  onState: (state: State) => void;
  onSelected: () => void;
}) {
  const [filters, setFilters] = useState<Filters>({
    name: player.card.player || player.name.replace(/['’].*$/, ""),
    stars: player.card.stars ?? null,
    kind: player.card.kind ?? null,
    season: null,
    concept: null,
    live_version: player.observed_live_version ?? player.card.live_version ?? null,
    offset: 0,
  });
  const [result, setResult] = useState<CatalogResult | null>(null);
  const [selected, setSelected] = useState<Card | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    setSelected(null);
    setConfirmed(false);
    const timer = setTimeout(
      () =>
        api<CatalogResult>("catalog", player.slot, filters)
          .then((data) => {
            if (active) {
              setResult(data);
              setError("");
            }
          })
          .catch((error) => {
            if (active) setError(error.message);
          })
          .finally(() => {
            if (active) setLoading(false);
          }),
      180,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [filters, player.slot]);
  function filter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((old) => ({
      ...old,
      [key]: value,
      offset: key === "offset" ? Number(value) : 0,
      ...(!["season", "offset"].includes(key) ? { season: null } : {}),
      ...(key === "kind" && value !== 1 ? { concept: null } : {}),
      ...(key === "kind" && value !== null && value !== 0 ? { live_version: null } : {}),
    }));
  }
  const mismatch = (!!selected && !!player.observed_live_version && selected.live_version !== player.observed_live_version) || !!selected?.base_comparison?.some(
    (c) => c.status !== "match",
  );
  async function choose() {
    if (!selected?.id) return;
    setSaving(true);
    setError("");
    try {
      const state = await api<State>(
        "select_card",
        player.slot,
        selected.id,
        confirmed,
        version,
      );
      onState(state);
      onSelected();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog
      title="저장된 카드에서 선택"
      className="catalog-dialog"
      onClose={onClose}
      busy={saving}
    >
      <div className="dialog-header">
        <div>
          <span className="eyebrow">CARD LIBRARY</span>
          <h2>
            맞는 카드를 찾아볼까요?
            <span className="position">{player.slot}</span>
          </h2>
          <p>성급·라이브 버전으로 좁히고 기본 능력치 6개를 대조하세요. 미페 배지: {player.observed_live_version ? `V${player.observed_live_version}` : "미인식 · 직접 선택 가능"}</p>
        </div>
        <button
          className="icon-button"
          aria-label="카드 선택 닫기"
          disabled={saving}
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      <fieldset className="catalog-filters" disabled={saving}>
        <label className="field">
          성급
          <select
            value={filters.stars ?? ""}
            onChange={(e) =>
              filter("stars", e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">전체 성급</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option value={n} key={n}>
                {n}성
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          카드 종류
          <select
            value={filters.kind ?? ""}
            onChange={(e) =>
              filter(
                "kind",
                e.target.value !== "" ? Number(e.target.value) : null,
              )
            }
          >
            <option value="">전체 종류</option>
            {Object.entries(options.kinds).map(([label, value]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field name-filter">
          선수 이름
          <input
            value={filters.name}
            onChange={(e) => filter("name", e.target.value)}
            placeholder="이름 일부만 입력해도 돼요"
          />
        </label>
        <label className="field">
          연도
          <select
            value={filters.season ?? ""}
            onChange={(e) =>
              filter(
                "season",
                e.target.value === "none"
                  ? "none"
                  : e.target.value
                    ? Number(e.target.value)
                    : null,
              )
            }
          >
            <option value="">전체 연도</option>
            {result?.years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
            {result?.no_year && <option value="none">연도 없음</option>}
          </select>
        </label>
        <label className="field">
          라이브 버전
          <select
            disabled={filters.kind !== null && filters.kind !== 0}
            value={filters.live_version ?? ""}
            onChange={(e) => filter("live_version", e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">전체 버전</option>
            {[1, 2, 3].map((n) => <option value={n} key={n}>V{n}</option>)}
          </select>
        </label>
        <label className="field concept-filter">
          임팩트 컨셉
          <select
            disabled={filters.kind !== 1}
            value={filters.concept ?? ""}
            onChange={(e) =>
              filter("concept", e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">전체 컨셉</option>
            {Object.entries(options.concepts).map(([label, value]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="text-button reset-filters"
          onClick={() =>
            setFilters({
              name: "",
              stars: null,
              kind: null,
              season: null,
              concept: null,
              live_version: null,
              offset: 0,
            })
          }
        >
          초기화
        </button>
      </fieldset>
      {error && (
        <div className="error-banner catalog-error" role="alert">
          <CircleAlert size={16} />
          <span>{error}</span>
        </div>
      )}
      <div className="catalog-summary">
        <span>
          검색 결과 <strong>{result?.total.toLocaleString() ?? "—"}</strong>장
        </span>
        <span>
          {loading ? (
            <>
              <Spinner />
              검색 중
            </>
          ) : (
            "기본 능력치 차이가 적은 카드부터 표시합니다."
          )}
        </span>
      </div>
      <div className="catalog-table-scroll">
        <table className="catalog-table">
          <thead>
            <tr>
              <th>선택</th>
              <th>카드</th>
              <th>종류 · 컨셉</th>
              <th>연도</th>
              <th>
                기본 능력치{" "}
                <small>파워 / 정확 / 선구 / 인내 / 주루 / 수비</small>
              </th>
              <th>대조</th>
            </tr>
          </thead>
          <tbody>
            {result?.items.map((card) => (
              <tr
                key={card.id}
                className={selected?.id === card.id ? "selected" : ""}
                onClick={() => {
                  setSelected(card);
                  setConfirmed(false);
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(card);
                    setConfirmed(false);
                  }
                }}
              >
                <td>
                  <input
                    type="radio"
                    name="catalog-card"
                    checked={selected?.id === card.id}
                    onChange={() => {
                      setSelected(card);
                      setConfirmed(false);
                    }}
                    aria-label={`${card.name} ${cardKind(card)} ${card.season} 카드 선택`}
                  />
                </td>
                <td>
                  <strong>{card.name}</strong>
                  <span className="star-label">
                    {card.stars}성 · #{card.id}
                  </span>
                </td>
                <td>{cardKind(card)}</td>
                <td>{card.season && card.season < 2101 ? card.season : "—"}</td>
                <td>
                  <span className="base-values">
                    {card.base_comparison?.map((c) => c.database).join(" / ")}
                  </span>
                </td>
                <td>
                  <span
                    className={`comparison-badge ${card.base_comparison?.every((c) => c.status === "match") ? "same" : "different"}`}
                  >
                    {card.base_comparison?.every(
                      (c) => c.status === "match",
                    ) ? (
                      <>
                        <Check size={13} />
                        모두 일치
                      </>
                    ) : (
                      `확인 ${card.base_comparison?.filter((c) => c.status !== "match").length}칸`
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !result?.items.length && (
          <div className="empty-state">
            <Search size={30} />
            <h3>조건에 맞는 카드가 없어요</h3>
            <p>성급·종류 조건을 풀거나 선수명을 확인해 보세요.</p>
          </div>
        )}
      </div>
      {result && result.total > result.limit && (
        <div className="catalog-pagination">
          <span>
            {result.offset + 1}–
            {Math.min(result.offset + result.limit, result.total)} /{" "}
            {result.total.toLocaleString()}장
          </span>
          <button
            className="icon-button"
            aria-label="이전 카드 목록"
            disabled={loading || result.offset === 0}
            onClick={() =>
              filter("offset", Math.max(0, result.offset - result.limit))
            }
          >
            <ChevronLeft size={17} />
          </button>
          <button
            className="icon-button"
            aria-label="다음 카드 목록"
            disabled={loading || result.offset + result.limit >= result.total}
            onClick={() => filter("offset", result.offset + result.limit)}
          >
            <ChevronRight size={17} />
          </button>
        </div>
      )}
      <div className="card-comparison">
        <div className="comparison-title">
          <h3>
            {selected
              ? selected.name
              : "카드를 선택하면 기본 능력치를 비교해요"}
          </h3>
          <span>훈련·강화 등 추가 능력치 제외</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>기본 능력치</th>
              {options.stats.map((stat) => (
                <th key={stat}>{stat}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>수집한 값</th>
              {options.stats.map((stat) => (
                <td key={stat}>{player.stats["기본"]?.[stat] ?? "—"}</td>
              ))}
            </tr>
            <tr>
              <th>선택 카드</th>
              {options.stats.map((stat) => {
                const comparison = selected?.base_comparison?.find(
                  (c) => c.stat === stat,
                );
                return (
                  <td
                    key={stat}
                    className={
                      comparison && comparison.status !== "match"
                        ? "stat-diff"
                        : ""
                    }
                  >
                    {comparison?.database ?? "—"}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="dialog-footer catalog-footer">
        <div>
          {mismatch ? (
            <label className="confirm-mismatch">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              기본값·라이브 버전의 누락과 차이를 확인하고 이 카드를 선택합니다.
            </label>
          ) : (
            <span className="muted">
              <ShieldCheck size={15} />
              수집한 능력치 숫자는 그대로 유지합니다.
            </span>
          )}
        </div>
        <div>
          <button
            className="button secondary"
            onClick={onClose}
            disabled={saving}
          >
            취소
          </button>
          <button
            className="button primary"
            disabled={
              !selected || loading || saving || (mismatch && !confirmed)
            }
            onClick={choose}
          >
            {saving ? <Spinner /> : <Link2 size={16} />}선택한 카드 연결
          </button>
        </div>
      </div>
    </Dialog>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
