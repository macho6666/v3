import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .cache import delete_cache, load_cache, save_cache
from .candidates import build_candidates
from .epub import analyze_epub, convert_epub
from .models import Candidate
from .naver import NaverSeriesScraper
from .text_utils import normalize


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("EPUB 회차 제목 자동 변환기 v2.1")
        self.geometry("1260x860")
        self.minsize(1050, 720)

        self.episodes = {}
        self.expected_total = None
        self.candidates = []
        self.analysis = {}
        self.epub_path = None
        self.events = queue.Queue()

        self._build()
        self.after(100, self._poll)

    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        step1 = ttk.Labelframe(root, text="1. 네이버 시리즈 회차 수집", padding=10)
        step1.pack(fill="x")

        row1 = ttk.Frame(step1)
        row1.pack(fill="x")

        self.url_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.url_var).pack(
            side="left",
            fill="x",
            expand=True,
        )

        ttk.Button(row1, text="저장 목록", command=self.load_saved).pack(
            side="left",
            padx=(8, 0),
        )

        self.fetch_btn = ttk.Button(row1, text="전체 수집", command=self.fetch_all)
        self.fetch_btn.pack(side="left", padx=(8, 0))

        ttk.Button(row1, text="최신화 확인", command=self.refresh_cache).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(row1, text="캐시 삭제", command=self.delete_saved).pack(
            side="left",
            padx=(8, 0),
        )

        self.collect_status = tk.StringVar(value="대기 중")
        ttk.Label(step1, textvariable=self.collect_status).pack(
            anchor="w",
            pady=(6, 0),
        )

        step2 = ttk.Labelframe(root, text="2. EPUB 선택 및 비교 분석", padding=10)
        step2.pack(fill="x", pady=(10, 0))

        row2 = ttk.Frame(step2)
        row2.pack(fill="x")

        self.epub_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.epub_var, state="readonly").pack(
            side="left",
            fill="x",
            expand=True,
        )

        ttk.Button(row2, text="EPUB 선택", command=self.choose_epub).pack(
            side="left",
            padx=(8, 0),
        )

        self.analyze_btn = ttk.Button(
            row2,
            text="비교 분석",
            command=self.start_analysis,
            state="disabled",
        )
        self.analyze_btn.pack(side="left", padx=(8, 0))

        step3 = ttk.Labelframe(root, text="3. 미리보기 · 선택 · 수정", padding=8)
        step3.pack(fill="both", expand=True, pady=(10, 0))

        tools = ttk.Frame(step3)
        tools.pack(fill="x", pady=(0, 6))

        ttk.Button(
            tools,
            text="선택 포함",
            command=lambda: self.set_selected(True),
        ).pack(side="left")

        ttk.Button(
            tools,
            text="선택 제외",
            command=lambda: self.set_selected(False),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            tools,
            text="제목 수정",
            command=self.edit_selected,
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            tools,
            text="중복 분석 보기",
            command=self.show_duplicate_analysis,
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            tools,
            text="전체 제외",
            command=lambda: self.set_all(False),
        ).pack(side="left", padx=(16, 0))

        ttk.Button(
            tools,
            text="로그 저장",
            command=self.save_log,
        ).pack(side="right")

        columns = ("apply", "episode", "kind", "title", "count", "status", "preview")
        self.tree = ttk.Treeview(
            step3,
            columns=columns,
            show="headings",
            selectmode="extended",
        )

        definitions = {
            "apply": ("적용", 55),
            "episode": ("회차", 65),
            "kind": ("후보", 55),
            "title": ("비교 제목", 320),
            "count": ("발견수", 70),
            "status": ("상태", 120),
            "preview": ("변환 결과", 430),
        }

        for name, (label, width) in definitions.items():
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, anchor="w")

        yscroll = ttk.Scrollbar(step3, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(step3, orient="horizontal", command=self.tree.xview)

        self.tree.configure(
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")

        self.tree.bind("<Double-1>", lambda event: self.edit_selected())

        step4 = ttk.Labelframe(root, text="4. 변환 시작", padding=10)
        step4.pack(fill="x", pady=(10, 0))

        row4 = ttk.Frame(step4)
        row4.pack(fill="x")

        ttk.Label(row4, text="태그").pack(side="left")

        self.heading_var = tk.StringVar(value="h2")
        ttk.Combobox(
            row4,
            textvariable=self.heading_var,
            values=("h1", "h2", "h3"),
            width=5,
            state="readonly",
        ).pack(side="left", padx=(6, 0))

        self.convert_btn = ttk.Button(
            row4,
            text="변환 시작",
            command=self.convert,
            state="disabled",
        )
        self.convert_btn.pack(side="right")

        self.final_status = tk.StringVar(
            value="비교 분석 후 변환 항목을 확인하세요."
        )
        ttk.Label(step4, textvariable=self.final_status).pack(
            anchor="w",
            pady=(6, 0),
        )

        log_frame = ttk.Labelframe(root, text="로그", padding=6)
        log_frame.pack(fill="both", pady=(10, 0))

        self.log_box = tk.Text(
            log_frame,
            height=8,
            state="disabled",
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True)

    def log(self, message: str):
        self.events.put(("log", message))

    def _poll(self):
        try:
            while True:
                event, payload = self.events.get_nowait()

                if event == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")

                elif event == "fetch_done":
                    self._apply_web_result(*payload)

                elif event == "analysis_done":
                    self._apply_analysis(payload)

                elif event == "error":
                    self.fetch_btn.configure(state="normal")
                    self.analyze_btn.configure(state="normal")
                    messagebox.showerror("오류", payload)

        except queue.Empty:
            pass

        self.after(100, self._poll)

    def _url(self):
        url = self.url_var.get().strip()

        if not url.startswith(("http://", "https://")):
            messagebox.showwarning(
                "URL 확인",
                "네이버 시리즈 작품 URL을 입력하세요.",
            )
            return None

        return url

    def fetch_all(self):
        url = self._url()
        if not url:
            return

        self.fetch_btn.configure(state="disabled")
        self.collect_status.set("전체 회차 수집 중...")

        def worker():
            try:
                result = NaverSeriesScraper(self.log).fetch(url)
                self.events.put(("fetch_done", (*result, True)))
            except Exception as exc:
                self.events.put(
                    ("error", f"{exc}\n\n{traceback.format_exc()}")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_web_result(self, episodes, duplicates, expected_total, save):
        self.fetch_btn.configure(state="normal")

        self.episodes = episodes
        self.expected_total = expected_total
        self.candidates = build_candidates(episodes)

        missing = []

        if episodes:
            max_number = expected_total or max(episodes)
            missing = [
                number
                for number in range(1, max_number + 1)
                if number not in episodes
            ]

        self.collect_status.set(
            f"회차 {len(episodes)}개 · 후보 {len(self.candidates)}개 · "
            f"누락 {len(missing)}개 · 중복 번호 {len(duplicates)}개"
        )

        if save and not missing:
            path = save_cache(
                self.url_var.get().strip(),
                episodes,
                expected_total,
            )
            self.log(f"캐시 저장: {path}")

        if self.epub_path and episodes:
            self.analyze_btn.configure(state="normal")

        if missing:
            messagebox.showwarning(
                "수집 불완전",
                f"누락 회차가 {len(missing)}개 있습니다.",
            )
        else:
            messagebox.showinfo(
                "수집 완료",
                f"{len(episodes)}개 회차를 불러왔습니다.",
            )

    def load_saved(self):
        url = self._url()
        if not url:
            return

        cached = load_cache(url)

        if not cached:
            messagebox.showinfo(
                "저장 목록 없음",
                "이 URL의 저장 목록이 없습니다.",
            )
            return

        self.episodes = cached["episodes"]
        self.expected_total = cached["expected_total"]
        self.candidates = build_candidates(self.episodes)

        self.collect_status.set(
            f"저장 목록 {len(self.episodes)}개 · 저장일 {cached['saved_at']}"
        )
        self.log(f"캐시 불러오기: {cached['path']}")

        if self.epub_path:
            self.analyze_btn.configure(state="normal")

    def refresh_cache(self):
        url = self._url()
        if not url:
            return

        if not load_cache(url):
            if messagebox.askyesno(
                "저장 목록 없음",
                "전체 수집을 진행할까요?",
            ):
                self.fetch_all()
            return

        self.fetch_all()

    def delete_saved(self):
        url = self._url()
        if not url:
            return

        messagebox.showinfo(
            "캐시 삭제",
            "삭제했습니다."
            if delete_cache(url)
            else "삭제할 캐시가 없습니다.",
        )

    def choose_epub(self):
        path = filedialog.askopenfilename(
            filetypes=[("EPUB 파일", "*.epub")]
        )

        if path:
            self.epub_path = Path(path)
            self.epub_var.set(path)

            self.clear_table()
            self.convert_btn.configure(state="disabled")

            if self.candidates:
                self.analyze_btn.configure(state="normal")

    def start_analysis(self):
        if not self.epub_path or not self.candidates:
            return

        self.analyze_btn.configure(state="disabled")
        self.convert_btn.configure(state="disabled")
        self.final_status.set("EPUB 비교 분석 중...")

        epub_path = self.epub_path
        candidates = list(self.candidates)

        def worker():
            try:
                result = analyze_epub(epub_path, candidates)
                self.events.put(("analysis_done", result))
            except Exception as exc:
                self.events.put(
                    ("error", f"{exc}\n\n{traceback.format_exc()}")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_analysis(self, result):
        self.clear_table()
        self.analysis = result

        matched_numbers = [
            candidate.episode_number
            for candidate in result.values()
            if candidate.found_count > 0
        ]

        max_found = max(matched_numbers) if matched_numbers else 0

        for candidate in result.values():
            if candidate.status == "미발견":
                matched_numbers = [
                    item.episode_number
                    for item in result.values()
                    if item.found_count > 0
                ]
                max_found = max(matched_numbers) if matched_numbers else 0
                if max_found and candidate.episode_number > max_found:
                    candidate.status = "최신화 범위 밖"
            self.refresh_row(candidate)

        normal = sum(
            candidate.status == "정상"
            for candidate in result.values()
        )
        duplicate = sum(
            "중복" in candidate.status
            or "같은제목" in candidate.status
            or "동일제목" in candidate.status
            for candidate in result.values()
        )
        missing = sum(
            candidate.found_count == 0
            for candidate in result.values()
        )

        self.log(f"정상 {normal} · 중복/동일제목 {duplicate} · 미발견 {missing}")
        self.analyze_btn.configure(state="normal")
        self.update_convert_state()

    def clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.analysis = {}

    def refresh_row(self, candidate: Candidate):
        values = (
            "포함" if candidate.include else "제외",
            f"{candidate.episode_number}화",
            candidate.kind,
            candidate.compare_title,
            candidate.found_count,
            candidate.status,
            (
                f"<{self.heading_var.get()}>"
                f"{candidate.episode_number}화 {candidate.output_title}"
                f"</{self.heading_var.get()}>"
            ),
        )

        if self.tree.exists(candidate.candidate_id):
            self.tree.item(candidate.candidate_id, values=values)
        else:
            self.tree.insert(
                "",
                "end",
                iid=candidate.candidate_id,
                values=values,
            )

    def set_selected(self, include: bool):
        for candidate_id in self.tree.selection():
            candidate = self.analysis[candidate_id]
            candidate.include = include
            self.refresh_row(candidate)

        self.update_convert_state()

    def set_all(self, include: bool):
        for candidate in self.analysis.values():
            candidate.include = include
            self.refresh_row(candidate)

        self.update_convert_state()

    def edit_selected(self):
        selection = self.tree.selection()

        if len(selection) != 1:
            messagebox.showinfo(
                "항목 선택",
                "한 개의 후보를 선택하세요.",
            )
            return

        candidate = self.analysis[selection[0]]

        new_title = simpledialog.askstring(
            "제목 수정",
            "EPUB에서 찾을 제목을 입력하세요.",
            initialvalue=candidate.compare_title,
            parent=self,
        )

        if new_title is None:
            return

        new_title = normalize(new_title)

        if not new_title:
            return

        candidate.compare_title = new_title
        candidate.output_title = new_title
        candidate.status = "사용자 수정"
        candidate.include = True

        self.refresh_row(candidate)
        self.update_convert_state()



    def show_duplicate_analysis(self):
        selection = self.tree.selection()

        if len(selection) != 1:
            messagebox.showinfo(
                "항목 선택",
                "중복 분석을 볼 후보 한 개를 선택하세요.",
            )
            return

        candidate = self.analysis[selection[0]]

        dialog = tk.Toplevel(self)
        dialog.title(
            f"{candidate.episode_number}화 중복 분석"
        )
        dialog.geometry("980x560")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text=(
                f"{candidate.episode_number}화 {candidate.output_title}\n"
                f"판단: {candidate.status}\n"
                f"이유: {candidate.duplicate_reason}"
            ),
        ).pack(anchor="w", padx=12, pady=10)

        columns = (
            "index",
            "file",
            "group",
            "before",
            "current",
            "after",
            "body",
        )
        tree = ttk.Treeview(
            dialog,
            columns=columns,
            show="headings",
        )

        definitions = {
            "index": ("번호", 50),
            "file": ("파일", 150),
            "group": ("연속수", 60),
            "before": ("앞 문단", 150),
            "current": ("현재 제목", 150),
            "after": ("뒤 문단", 150),
            "body": ("본문 미리보기", 250),
        }

        for name, (label, width) in definitions.items():
            tree.heading(name, text=label)
            tree.column(name, width=width, anchor="w")

        for index, location in enumerate(candidate.matches):
            tree.insert(
                "",
                "end",
                values=(
                    index + 1,
                    location.file_path,
                    location.consecutive_group_size,
                    location.previous_text[:100],
                    location.current_text[:100],
                    location.next_text[:100],
                    location.body_preview[:180],
                ),
            )

        tree.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=(0, 12))

        def keep_all():
            candidate.duplicate_action = "keep_all"
            candidate.status = "사용자 선택 · 모두 유지"
            candidate.include = True
            self.refresh_row(candidate)
            self.update_convert_state()
            dialog.destroy()

        def delete_duplicates():
            candidate.duplicate_action = "delete_duplicate_sections"
            candidate.status = "사용자 선택 · 뒤쪽 중복 삭제"
            candidate.include = True
            self.refresh_row(candidate)
            self.update_convert_state()
            dialog.destroy()

        ttk.Button(
            buttons,
            text="모두 유지",
            command=keep_all,
        ).pack(side="right")

        ttk.Button(
            buttons,
            text="뒤쪽 중복 삭제",
            command=delete_duplicates,
        ).pack(side="right", padx=(0, 6))

        ttk.Button(
            buttons,
            text="닫기",
            command=dialog.destroy,
        ).pack(side="right", padx=(0, 6))

    def update_convert_state(self):
        count = sum(
            candidate.include
            for candidate in self.analysis.values()
        )

        self.convert_btn.configure(
            state="normal" if count else "disabled"
        )

        self.final_status.set(
            f"변환 예정 {count}개"
            if count
            else "변환 항목 없음"
        )

    def save_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("텍스트 파일", "*.txt")],
            initialfile="analysis_log.txt",
        )

        if not path:
            return

        lines = []

        for candidate in sorted(
            self.analysis.values(),
            key=lambda item: (
                item.episode_number,
                item.candidate_id,
            ),
        ):
            lines.append(
                f"{candidate.episode_number}화\t"
                f"{candidate.kind}\t"
                f"{candidate.compare_title}\t"
                f"발견 {candidate.found_count}회\t"
                f"{candidate.status}\t"
                f"{'포함' if candidate.include else '제외'}"
            )

        Path(path).write_text(
            "\n".join(lines),
            encoding="utf-8-sig",
        )

    def convert(self):
        selected = [
            candidate
            for candidate in self.analysis.values()
            if candidate.include
        ]

        if not selected or not self.epub_path:
            return

        if not messagebox.askyesno(
            "변환 확인",
            f"{len(selected)}개 후보를 변환합니다.\n"
            "연속 중복은 하나만 남기고 나머지 제목을 삭제합니다.\n"
            "떨어진 중복은 두 번째 제목부터 다음 에피소드 제목 직전까지 삭제합니다.\n"
            "계속할까요?",
        ):
            return

        destination = self.epub_path.with_name(
            self.epub_path.stem + "_제목변환.epub"
        )

        try:
            result = convert_epub(
                self.epub_path,
                destination,
                selected,
                self.analysis.values(),
                self.heading_var.get(),
            )

            log_path = destination.with_suffix(".log.txt")

            log_lines = [
                f"변경 파일: {result['changed_files']}",
                f"변경 제목: {result['changed_titles']}",
                f"삭제 문단: {result['deleted_paragraphs']}",
                f"미발견: {len(result['missing'])}",
                f"충돌: {len(result['collisions'])}",
                f"경고: {len(result['warnings'])}",
                "",
                "[미발견]",
                *result["missing"],
                "",
                "[충돌]",
                *result["collisions"],
                "",
                "[경고]",
                *result["warnings"],
            ]

            log_path.write_text(
                "\n".join(log_lines),
                encoding="utf-8-sig",
            )

            messagebox.showinfo(
                "변환 완료",
                f"저장:\n{destination}\n\n"
                f"변경 {result['changed_titles']}개\n"
                f"삭제 문단 {result['deleted_paragraphs']}개\n"
                f"미발견 {len(result['missing'])}개",
            )

        except Exception as exc:
            messagebox.showerror(
                "변환 오류",
                f"{exc}\n\n{traceback.format_exc()}",
            )
