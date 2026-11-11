# -*- coding: utf-8 -*-
"""PChome 商品價格爬蟲 + 視覺化 (Streamlit)

執行方式：streamlit run pchome_app.py
"""
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 價格區間 (用於圓餅圖、旭日圖)
PRICE_BINS = [0, 300, 500, 1000, 2000, 5000, float("inf")]
PRICE_LABELS = ["0-300", "301-500", "501-1000", "1001-2000", "2001-5000", "5000以上"]

st.set_page_config(page_title="PChome 價格分析", page_icon="🛒", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def fetch_page(keyword: str, page: int) -> list:
    """抓取單一頁面的商品資料 (快取 10 分鐘，避免重複請求)。"""
    params = {"q": keyword, "page": page, "sort": "sale/dc"}
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("prods", [])


def crawl(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    """爬取多頁資料並合併成 DataFrame。"""
    frames = []
    progress = st.progress(0.0, text="準備開始爬取…")
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"正在爬取第 {i} / {pages} 頁…")
        prods = fetch_page(keyword, i)
        if not prods:  # 後面已沒有資料就提早結束
            st.info(f"第 {i} 頁沒有資料，已停止爬取。")
            break
        frames.append(pd.DataFrame(prods))
        if i < pages:
            time.sleep(delay)  # 禮貌性延遲，避免被網站封鎖
    progress.progress(1.0, text="爬取完成")
    progress.empty()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """整理欄位：名稱、價格、價格區間、品牌 (取商品名稱第一個詞)。"""
    out = df[["name", "price"]].copy()
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["price"]).reset_index(drop=True)
    out["價格區間"] = pd.cut(out["price"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True)
    brand = out["name"].astype(str).str.split().str[0]
    top_brands = brand.value_counts().head(10).index  # 只保留前 10 大，其餘歸「其他」
    out["品牌"] = brand.where(brand.isin(top_brands), "其他")
    return out


# ───────────────────────── 介面 ─────────────────────────
st.title("🛒 PChome 商品價格分析")
st.caption("輸入商品關鍵字與要爬取的頁數，自動繪製折線圖、圓餅圖與旭日圖。")

with st.sidebar:
    st.header("搜尋條件")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.0, 0.5,
                      help="間隔越長越不容易被網站封鎖")
    run = st.button("開始爬取", type="primary", width="stretch")

if run:
    if not keyword.strip():
        st.warning("請先輸入產品名稱。")
    else:
        try:
            t0 = time.time()
            raw = crawl(keyword.strip(), int(pages), delay)
            if raw.empty:
                st.session_state.pop("result", None)
                st.error("查無資料，請換個關鍵字試試。")
            else:
                st.session_state["result"] = {
                    "keyword": keyword.strip(),
                    "raw": raw,
                    "data": prepare(raw),
                    "elapsed": time.time() - t0,
                }
        except requests.RequestException as e:
            st.error(f"連線失敗：{e}")
        except ValueError as e:
            st.error(f"資料解析失敗 (回傳內容可能不是 JSON)：{e}")

result = st.session_state.get("result")
if result:
    data, raw, kw = result["data"], result["raw"], result["keyword"]

    st.success(f"「{kw}」共取得 {len(data)} 筆商品，耗時 {result['elapsed']:.1f} 秒")

    c1, c2, c3 = st.columns(3)
    c1.metric("平均價格", f"{data['price'].mean():,.0f}")
    c2.metric("最高價格", f"{data['price'].max():,.0f}")
    c3.metric("最低價格", f"{data['price'].min():,.0f}")

    tab1, tab2, tab3, tab4 = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📋 資料表"])

    with tab1:
        max_n = max(len(data), 1)
        n = st.slider("顯示前幾筆商品", 1, max_n, min(70, max_n)) if max_n > 1 else 1
        view = data.head(n).reset_index().rename(columns={"index": "商品序號", "price": "價格"})
        fig = px.line(view, x="商品序號", y="價格", hover_name="name", markers=True,
                      title=f"PChome 電商網站上「{kw}」售價")
        fig.add_hline(y=data["price"].mean(), line_dash="dash", line_color="red",
                      annotation_text=f"平均 {data['price'].mean():,.0f}")
        st.plotly_chart(fig, width="stretch")

    with tab2:
        pie_df = (data.groupby("價格區間", observed=True).size()
                  .reset_index(name="數量"))
        fig = px.pie(pie_df, names="價格區間", values="數量", hole=0.3,
                     title=f"「{kw}」價格區間分佈")
        fig.update_traces(textinfo="label+percent")
        st.plotly_chart(fig, width="stretch")

    with tab3:
        sun_df = (data.groupby(["價格區間", "品牌"], observed=True).size()
                  .reset_index(name="數量"))
        fig = px.sunburst(sun_df, path=["價格區間", "品牌"], values="數量",
                          title=f"「{kw}」價格區間 × 品牌 (品牌取商品名稱第一個詞)")
        fig.update_layout(height=650)
        st.plotly_chart(fig, width="stretch")

    with tab4:
        st.dataframe(data[["name", "price", "價格區間", "品牌"]], width="stretch")
        stamp = datetime.now().strftime("%Y%m%d")
        st.download_button(
            "下載完整資料 (CSV)",
            raw.to_csv(index=False).encode("utf-8-sig"),  # utf-8-sig 讓 Excel 開啟不亂碼
            file_name=f"{stamp}_PCHOME_{kw}.csv",
            mime="text/csv",
        )
else:
    st.info("👈 請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
