import re
import time
from typing import Callable, Dict, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TOTAL_RE = re.compile(r"총\s*([\d,]+)\s*화")
EP_RE = re.compile(r"^\s*(\d{1,6})\s*화\s+(.+?)\s*$")
DATE_RE = re.compile(r"\s*\(\d{4}\.\d{1,2}\.\d{1,2}\.?\)\s*$")


def force_asc(url: str) -> str:
    parts = urlsplit(url.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["sortOrder"] = "ASC"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def parse_episode_lines(text: str) -> Tuple[Dict[int, str], Set[int]]:
    episodes: Dict[int, str] = {}
    duplicates: Set[int] = set()

    for raw in text.splitlines():
        line = " ".join(raw.replace("\xa0", " ").split()).strip()

        if not line or line in {"미리보기", "보기"}:
            continue

        line = DATE_RE.sub("", line).strip()
        match = EP_RE.match(line)

        if not match:
            continue

        number = int(match.group(1))
        title = match.group(2).strip()

        if number in episodes and episodes[number] != title:
            duplicates.add(number)

        episodes[number] = title

    return episodes, duplicates


class NaverSeriesScraper:
    def __init__(self, log: Callable[[str], None]):
        self.log = log

    def fetch(self, url: str) -> Tuple[Dict[int, str], Set[int], Optional[int]]:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--lang=ko-KR")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        self.log("Chrome 실행 중...")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(60)

        episodes: Dict[int, str] = {}
        duplicates: Set[int] = set()
        expected_total: Optional[int] = None

        try:
            target = force_asc(url)
            self.log(f"접속: {target}")
            driver.get(target)

            wait = WebDriverWait(driver, 20)
            wait.until(lambda d: d.find_element(By.TAG_NAME, "body").text.strip() != "")
            time.sleep(2)

            body = driver.find_element(By.TAG_NAME, "body").text
            total_match = TOTAL_RE.search(body)
            if total_match:
                expected_total = int(total_match.group(1).replace(",", ""))
                self.log(f"페이지 표시 총 회차: {expected_total}")

            no_change_count = 0

            for _ in range(500):
                try:
                    current_page = int(
                        driver.find_element(
                            By.CSS_SELECTOR,
                            "#volumeListPagenate strong",
                        ).text.strip()
                    )
                except Exception:
                    current_page = 1

                current, current_duplicates = parse_episode_lines(
                    driver.find_element(By.TAG_NAME, "body").text
                )
                duplicates |= current_duplicates

                before = len(episodes)

                for number, title in current.items():
                    if number in episodes and episodes[number] != title:
                        duplicates.add(number)
                    episodes[number] = title

                added = len(episodes) - before
                self.log(
                    f"{current_page}페이지: {added}개 추가 "
                    f"(누적 {len(episodes)}"
                    + (f"/{expected_total}" if expected_total else "")
                    + ")"
                )

                if expected_total and len(episodes) >= expected_total:
                    break

                next_clicked = False
                next_number = current_page + 1

                try:
                    links = driver.find_elements(
                        By.XPATH,
                        f"//*[@id='volumeListPagenate']//a[normalize-space(.)='{next_number}']",
                    )
                    for element in links:
                        if element.is_displayed() and element.is_enabled():
                            driver.execute_script("arguments[0].click();", element)
                            next_clicked = True
                            break
                except Exception:
                    pass

                if not next_clicked:
                    try:
                        links = driver.find_elements(
                            By.CSS_SELECTOR,
                            "#volumeListPagenate span.next a",
                        )
                        for element in links:
                            if element.is_displayed() and element.is_enabled():
                                driver.execute_script("arguments[0].click();", element)
                                next_clicked = True
                                break
                    except Exception:
                        pass

                if not next_clicked:
                    self.log("다음 페이지 버튼이 없어 수집을 종료합니다.")
                    break

                try:
                    wait.until(
                        lambda d: d.find_element(
                            By.CSS_SELECTOR,
                            "#volumeListPagenate strong",
                        ).text.strip() != str(current_page)
                    )
                    no_change_count = 0
                except Exception:
                    no_change_count += 1
                    self.log(f"페이지 전환 확인 실패: {current_page}페이지")

                time.sleep(1)

                if no_change_count >= 3:
                    self.log("페이지 전환이 3회 연속 실패했습니다.")
                    break

            return episodes, duplicates, expected_total

        finally:
            try:
                driver.quit()
            except Exception:
                pass
