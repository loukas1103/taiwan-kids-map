import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
import re
import time
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 1. 基本設定與 SSL 警告消除
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# 標準縣市清單
STANDARD_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

# ----------------------------------------------------------------
# 2. 資料核心處理函數
# ----------------------------------------------------------------
@st.cache_data(ttl=600) # 設定 10 分鐘快取，方便除錯
def load_all_data():
    all_pois = []
    
    # --- 方法 A: 觀光署政府 XML 資料 ---
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(gov_url, headers=headers, timeout=20, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                
                # 強效縣市歸類邏輯 (合併地址與區域判定)
                full_loc_str = (region + add).replace("台", "臺")
                found_city = "其他"
                for city in STANDARD_CITIES:
                    if city in full_loc_str or city[:2] in full_loc_str:
                        found_city = city
                        break
                
                px = info.find('Px').text.strip() if info.find('Px') is not None else None
                py = info.find('Py').text.strip() if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "介紹": (info.find('Description').text[:100] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px),
                        "來源": "政府資料"
                    })
            except:
                continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # --- 方法 B: Google 表單 CSV ---
    # 加上 timestamp 參數強制 Google 伺服器回傳最新版，不抓舊快取
    SHEET_BASE_URL = "
