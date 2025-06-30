import streamlit as st
import requests
import pandas as pd
import random
from fuzzywuzzy import fuzz
import re
import datetime
import os
import base64

# --- 常數設定 ---
try:
    API_KEY = st.secrets["API_KEY"]
except KeyError:
    st.error("錯誤：Streamlit Secrets 中未找到 'API_KEY'。請確保您已在 .streamlit/secrets.toml 中設定 API_KEY。")

EXCEL_FILE_PATH = "YT_weather_matched.xlsx"
MOVIE_POSTER_LOCAL_DIR = "movie"
WEATHER_CODES_FILE_PATH = "weather_codes.csv"
WEATHER_IMAGES_DIR = "images"

# 新增：天氣圖片支持的擴展名列表
IMAGE_EXTENSIONS = ['png', 'gif', 'jpg', 'jpeg']


# --- 輔助函數 ---

def set_background(image_file):
    with open(image_file, "rb") as image:
        encoded = base64.b64encode(image.read()).decode()

    st.markdown(f"""
        <style>
        .stApp {{
            background-image: url("data:image/jpg;base64,{encoded}");
            background-size: cover;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
    """, unsafe_allow_html=True)

def extract_youtube_id(url):
    """從YouTube URL中提取影片ID。"""
    match = re.search(r'(?:v=|youtu\.be/|embed/|live/)([a-zA-Z0-9_-]{11})', url)
    if match:
        return match.group(1)

    # 處理 googleusercontent.com 的特殊情況
    match_usercontent = re.search(r'googleusercontent\.com/youtube\.com/\d+([a-zA-Z0-9_-]+)', url)
    if match_usercontent:
        return match_usercontent.group(1)

    if "youtube.com/watch?v=" in url:
        return url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        parts = url.split("youtu.be/")
        if len(parts) > 1:
            return parts[1].split("?")[0]
    elif "googleusercontent.com/youtube.com/1" in url:
        parts = url.split("googleusercontent.com/youtube.com/1")
        if len(parts) > 1:
            return parts[1].split("?")[0]
    return None

# 新增輔助函數：將本地圖片轉換為 Base64 編碼的 HTML <img> 標籤
def load_local_image_as_base64(image_path, width=None, height=None):
    """
    載入本地圖片並轉換為 Base64 編碼的 HTML <img> 標籤。
    用於確保 GIF 動畫在 Streamlit Cloud 上正常播放。
    """
    if not image_path or not os.path.exists(image_path):
        return None

    file_extension = image_path.split('.')[-1].lower()
    # 這裡可以精簡，因為我們假設總是能找到圖片或預設圖片
    # if file_extension not in IMAGE_EXTENSIONS:
    #     return None

    try:
        with open(image_path, "rb") as f:
            contents = f.read()
        data_url = base64.b64encode(contents).decode("utf-8")

        style_attrs = []
        if width:
            style_attrs.append(f"width: {width}px;")
        if height:
            style_attrs.append(f"height: {height}px;")

        style_str = " ".join(style_attrs) if style_attrs else ""

        # 確保正確的 MIME 類型
        mime_type = f"image/{'jpeg' if file_extension == 'jpg' else file_extension}"

        return f'<img src="data:{mime_type};base64,{data_url}" alt="圖片" style="{style_str}">'
    except Exception as e:
        st.warning(f"無法載入圖片 {image_path} 為 Base64：{e}")
        return None

# 修改：簡化圖片路徑獲取邏輯，因為總是能匹配或有預設圖
def get_image_path_or_default(base_dir, code):
    """
    嘗試找到特定代碼的圖片。如果沒有，則找預設圖片。
    假設 code 總是有效，且圖片存在或預設圖存在。
    """
    for ext in IMAGE_EXTENSIONS:
        specific_path = os.path.join(base_dir, f"{code}.{ext}")
        if os.path.exists(specific_path):
            return specific_path

    # 如果特定代碼圖片不存在，則返回預設圖片的路徑
    for ext in IMAGE_EXTENSIONS:
        default_path = os.path.join(base_dir, f"default.{ext}")
        if os.path.exists(default_path):
            return default_path
    return None # 如果連預設圖片都找不到，則返回 None

@st.cache_data(ttl=3600)
def get_location_names():
    """從中央氣象署 API 獲取台灣縣市列表。"""
    url = f'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={API_KEY}'
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        if 'records' in data and 'location' in data['records']:
            return [loc['locationName'] for loc in data['records']['location']]
    except requests.exceptions.RequestException as e:
        st.error(f"錯誤：無法獲取縣市列表，請檢查網路或 API 金鑰：{e}")
    return ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

@st.cache_data(ttl=3600)
def get_weather_data(city_name):
    """根據城市名稱獲取天氣資訊，包含天氣描述、降雨機率、最低溫度和最高溫度。"""
    # API_KEY 不再在函數內部硬編碼或重複定義
    url = f'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={API_KEY}&locationName={city_name}'
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()

        if 'records' in data and 'location' in data['records'] and data['records']['location']:
            location_data = data['records']['location'][0]

            # 獲取天氣現象 (Wx)
            wx_element = next((elem for elem in location_data['weatherElement'] if elem['elementName'] == 'Wx'), None)
            if not wx_element:
                return {"status": "error", "display_text": f"無法取得 {city_name} 天氣資料：缺少 Wx 元素。"}

            time_elements = wx_element['time']
            valid_time_elements = []
            for item in time_elements:
                try:
                    # 嘗試解析 startTime，並確保其格式正確
                    datetime.datetime.strptime(item['startTime'], '%Y-%m-%d %H:%M:%S')
                    valid_time_elements.append(item)
                except ValueError:
                    pass

            if not valid_time_elements:
                return {"status": "error", "display_text": f"無法取得 {city_name} 天氣資料：預報時間數據無效。"}

            # 找到最接近當前時間的預報時段
            now = datetime.datetime.now()
            forecast = min(valid_time_elements,
                           key=lambda x: abs(datetime.datetime.strptime(x['startTime'], '%Y-%m-%d %H:%M:%S') - now))
            desc = forecast['parameter']['parameterName']
            start_dt = datetime.datetime.strptime(forecast['startTime'], '%Y-%m-%d %H:%M:%S')
            hour = start_dt.hour
            time_desc = "午夜到早晨" if 0 <= hour < 6 else "早晨到中午" if 6 <= hour < 12 else "中午到傍晚" if 12 <= hour < 18 else "傍晚到午夜"

            # 獲取降雨機率 (PoP)
            pop = "N/A"
            pop_element = next((elem for elem in location_data['weatherElement'] if elem['elementName'] == 'PoP'), None)

            if pop_element:
                pop_data_found = False
                for pop_time in pop_element['time']:
                    pop_start_dt = datetime.datetime.strptime(pop_time['startTime'], '%Y-%m-%d %H:%M:%S')
                    pop_end_dt = datetime.datetime.strptime(pop_time['endTime'], '%Y-%m-%d %H:%M:%S')

                    # 檢查預報時段是否包含在降雨機率時段內
                    if pop_start_dt <= start_dt < pop_end_dt:
                        pop = pop_time['parameter']['parameterName'] + "%"
                        pop_data_found = True
                        break

                if not pop_data_found and pop_element.get('time'):
                    # 如果沒有精確匹配，就取第一個時段的降雨機率
                    pop = pop_element['time'][0]['parameter']['parameterName'] + "%"

            # 獲取最低溫度 (MinT)
            min_temp = "N/A"
            min_temp_element = next((elem for elem in location_data['weatherElement'] if elem['elementName'] == 'MinT'), None)
            if min_temp_element:
                for temp_time in min_temp_element['time']:
                    temp_start_dt = datetime.datetime.strptime(temp_time['startTime'], '%Y-%m-%d %H:%M:%S')
                    temp_end_dt = datetime.datetime.strptime(temp_time['endTime'], '%Y-%m-%d %H:%M:%S')
                    if temp_start_dt <= start_dt < temp_end_dt:
                        min_temp = temp_time['parameter']['parameterName']
                        break
                if min_temp == "N/A" and min_temp_element.get('time'):
                    min_temp = min_temp_element['time'][0]['parameter']['parameterName']

            # 獲取最高溫度 (MaxT)
            max_temp = "N/A"
            max_temp_element = next((elem for elem in location_data['weatherElement'] if elem['elementName'] == 'MaxT'), None)
            if max_temp_element:
                for temp_time in max_temp_element['time']:
                    temp_start_dt = datetime.datetime.strptime(temp_time['startTime'], '%Y-%m-%d %H:%M:%S')
                    temp_end_dt = datetime.datetime.strptime(temp_time['endTime'], '%Y-%m-%d %H:%M:%S')
                    if temp_start_dt <= start_dt < temp_end_dt:
                        max_temp = temp_time['parameter']['parameterName']
                        break
                if max_temp == "N/A" and max_temp_element.get('time'):
                    max_temp = max_temp_element['time'][0]['parameter']['parameterName']

            # 組裝顯示文字，包含溫度
            display_text = (
                f"{city_name} {start_dt.month}/{start_dt.day} {time_desc}是：**{desc}**，"
                f"氣溫介於 **{min_temp}°C** 到 **{max_temp}°C**，降雨機率 **{pop}** 喔！"
            )

            return {
                "status": "success",
                "description": desc,
                "display_text": display_text,
                "min_temp": min_temp,
                "max_temp": max_temp,
                "pop": pop
            }

        return {"status": "error", "display_text": f"無法取得 {city_name} 天氣資料：資料結構異常或該縣市無預報資料。"}

    except requests.exceptions.RequestException as e:
        return {"status": "error", "display_text": f"無法取得 {city_name} 天氣資料：網路或 API 錯誤 ({e})。請檢查您的 API 金鑰是否有效。"}
    except Exception as e:
        return {"status": "error", "display_text": f"處理 {city_name} 天氣資料時發生錯誤: {e}"}


@st.cache_data(ttl=3600)
def initialize_videos(excel_path):
    """從指定的本地 Excel 檔案路徑讀取影片資料。"""
    try:
        df = pd.read_excel(excel_path)
        videos = []
        for index, row in df.iterrows():
            url = str(row.get('影片URL', '')).strip()
            desc = str(row.get('matched_weather_descriptions', '')).strip()
            song_title = str(row.get('歌曲名稱', desc.split(',')[0] if desc else '未知歌曲')).strip()
            if url and desc and not pd.isna(url):
                videos.append({'index': index, 'url': url, 'desc': desc, 'title': song_title})
        return videos
    except FileNotFoundError:
        st.error(f"錯誤：找不到 Excel 檔案 '{excel_path}'。請確保檔案存在且路徑正確。")
        return []
    except Exception as e:
        st.error(f"從本地 Excel 檔案讀取時發生錯誤: {e}")
        return []

@st.cache_data(ttl=3600)
def get_movie_poster_urls():
    """從本地 'movie' 資料夾獲取電影海報 URL 和名稱列表。"""
    movies = []
    if not os.path.isdir(MOVIE_POSTER_LOCAL_DIR):
        st.warning(f"找不到本地電影海報資料夾 '{MOVIE_POSTER_LOCAL_DIR}'。請確保資料夾存在。")
        return []

    try:
        for filename in os.listdir(MOVIE_POSTER_LOCAL_DIR):
            if os.path.isfile(os.path.join(MOVIE_POSTER_LOCAL_DIR, filename)) and \
               any(filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS): # 檢查所有圖片擴展名

                title = filename.rsplit('.', 1)[0]
                poster_url = os.path.join(MOVIE_POSTER_LOCAL_DIR, filename)

                movies.append({'title': title, 'poster_url': poster_url})

        if not movies:
            st.warning(f"在本地資料夾 '{MOVIE_POSTER_LOCAL_DIR}' 中未找到任何電影海報圖片。請確保您的資料夾中有 .jpg、.png 或 .gif 檔案。")
            return []

        return movies
    except Exception as e:
        st.error(f"從本地電影海報資料夾讀取時發生錯誤: {e}")
        return []

@st.cache_data(ttl=3600)
def load_weather_codes(csv_path):
    """從 CSV 檔案載入天氣描述與分類代碼的對應表。"""
    try:
        if not os.path.exists(csv_path):
            st.error(f"錯誤：找不到天氣代碼檔案 '{csv_path}'。請確保檔案存在且路徑正確。")
            return {}
        df = pd.read_csv(csv_path)
        return df.set_index('中文描述')['分類代碼'].to_dict()
    except Exception as e:
        st.error(f"從天氣代碼檔案讀取時發生錯誤: {e}")
        return {}


# 集中化 Session State 重置邏輯
def reset_recommendation_states():
    """重置所有推薦相關的 Streamlit Session State 變數。"""
    st.session_state.result_text = ""
    st.session_state.recommended_youtube_id = None
    st.session_state.recommended_image_url = None
    # 注意：這裡不重置音樂和電影的已推薦索引，它們有自己的內部重置邏輯
    st.session_state.recommended_weather_image_html = None # 現在存儲 HTML
    st.session_state.weather_image_caption_desc = None

def get_available_music_indices(all_videos):
    """獲取尚未推薦的音樂的**原始索引**，並處理重置邏輯。"""
    if 'recommended_music_original_indices' not in st.session_state:
        st.session_state.recommended_music_original_indices = set()

    all_original_indices = {video['index'] for video in all_videos}

    available_original_indices = list(all_original_indices - st.session_state.recommended_music_original_indices)

    if not available_original_indices and len(all_original_indices) > 0:
        st.session_state.recommended_music_original_indices = set()
        available_original_indices = list(all_original_indices)
        st.info("所有音樂都推薦過了，已重置音樂推薦列表。")

    return available_original_indices

def find_and_recommend_music(weather_desc, all_videos):
    """
    根據天氣描述推薦相關音樂，從尚未推薦的音樂中選擇。
    如果有多個匹配，則從這些匹配的歌曲中隨機選擇一個。
    """
    if not all_videos:
        return "音樂列表為空，無法推薦音樂。", None

    available_original_indices = get_available_music_indices(all_videos)
    available_videos = [video for video in all_videos if video['index'] in available_original_indices]

    if not available_videos:
        # 如果所有可用音樂都推薦過了，再次獲取已重置的列表
        available_original_indices = get_available_music_indices(all_videos) # 這會觸發重置提示
        available_videos = [video for video in all_videos if video['index'] in available_original_indices]
        if not available_videos: # 再次檢查，以防數據為空
            return "沒有可用的音樂可以隨機推薦了。", None

    matched_available_videos_with_score = []
    best_score_overall = -1
    for video in available_videos:
        score = fuzz.partial_ratio(weather_desc.lower(), video['desc'].lower())
        if score >= 30: # 保留您的最小匹配度
            matched_available_videos_with_score.append((video, score))
            if score > best_score_overall:
                best_score_overall = score

    selected_video = None
    if matched_available_videos_with_score:
        top_score_matches = [video_item for video_item, score_val in matched_available_videos_with_score if score_val == best_score_overall]
        selected_video = random.choice(top_score_matches)

    if selected_video:
        youtube_id = extract_youtube_id(selected_video['url'])
        st.session_state.recommended_music_original_indices.add(selected_video['index'])
        display_text = "這樣的天氣來聽這首療癒一下吧！"

        if youtube_id:
            return display_text, youtube_id
        else:
            return f"{display_text}\n(抱歉，無法從連結中提取影片ID。)", None
    else:
        return random_music_recommendation(all_videos) # 如果沒有精確匹配，則隨機推薦


def random_music_recommendation(all_videos, skip_info_reset=False):
    """隨機推薦一首音樂，並返回文字描述和 YouTube ID，確保不重複。"""
    if not all_videos:
        return "音樂列表為空，無法隨機推薦音樂。", None

    available_original_indices = get_available_music_indices(all_videos) # 這裡會處理重置邏輯和提示
    available_videos_for_random = [video for video in all_videos if video['index'] in available_original_indices]

    if not available_videos_for_random:
        # get_available_music_indices 已經處理了 info 提示，這裡無需再次提示
        return "沒有可用的音樂可以隨機推薦了。", None

    selected_video = random.choice(available_videos_for_random)
    st.session_state.recommended_music_original_indices.add(selected_video['index'])
    youtube_id = extract_youtube_id(selected_video['url'])

    if youtube_id:
        display_text = "已為您隨機推薦歌曲："
        return display_text, youtube_id
    else:
        display_text = "無法從連結中提取影片ID。請重新點選。"
        return display_text, None

def random_movie_recommendation(all_movies):
    """隨機推薦一部電影，並返回顯示名稱、海報 URL"""
    if not all_movies:
        return "電影列表為空，無法隨機推薦電影。", None, 0

    # 這裡將 recommended_movie_indices 設置為 set，提高效率
    if 'recommended_movie_indices' not in st.session_state:
        st.session_state.recommended_movie_indices = set()

    # 獲取所有電影的列表索引
    all_list_indices = set(range(len(all_movies)))
    available_indices = list(all_list_indices - st.session_state.recommended_movie_indices)

    if not available_indices:
        st.session_state.recommended_movie_indices = set() # 重置
        available_indices = list(all_list_indices)
        st.info("所有電影都推薦過了，已重置電影推薦列表。")

    selected_index = random.choice(available_indices)
    selected_movie = all_movies[selected_index]

    st.session_state.recommended_movie_indices.add(selected_index)

    remaining_count = len(available_indices) - 1

    return selected_movie['title'], selected_movie['poster_url'], remaining_count

MANUAL_CORRECTIONS = {
    "台北市": "臺北市", "台北": "臺北市", "北市": "臺北市", "北": "臺北市",
    "新北": "新北市", "臺北縣": "新北市",
    "桃園": "桃園市", "桃園縣": "桃園市", "桃": "桃園市", "園": "桃園市",
    "台中": "臺中市", "台中市": "臺中市", "台中縣": "臺中市", "臺中縣": "臺中市", "中縣": "臺中市", "中市": "臺中市", "臺中": "臺中市", "中": "臺中市",
    "台南": "臺南市", "台南市": "臺南市", "臺南": "臺南市", "台南縣": "臺南市", "臺南縣": "臺南市",
    "高雄": "高雄市", "雄市": "高雄市",  "雄": "高雄市", "高雄縣": "高雄市",
    "基隆": "基隆市", "基": "基隆市", "隆": "基隆市", "雞": "基隆市", "籠": "基隆市", "雞籠": "基隆市", "基隆縣": "基隆市", "基市": "基隆市", "隆市": "基隆市", "雞市": "基隆市", "籠市": "基隆市", "雞籠市": "基隆市", "雞籠縣": "基隆市", "雞縣": "基隆市", "籠縣": "基隆市",
    "新竹": "新竹市", "竹": "新竹市", "竹市": "新竹市", "竹縣": "新竹縣",
    "嘉義": "嘉義市", "嘉": "嘉義市", "義": "嘉義市", "嘉縣": "嘉義縣", "義縣": "嘉義縣",
    "苗栗": "苗栗縣", "苗": "苗栗縣", "栗": "苗栗縣", "栗縣": "苗栗縣", "苗縣": "苗栗縣", "苗栗市": "苗栗縣",
    "彰化": "彰化縣", "彰": "彰化縣", "化": "彰化縣", "彰縣": "彰化縣", "化縣": "彰化縣", "彰化市": "彰化縣",
    "南投": "南投縣", "投": "南投縣", "投縣": "南投縣", "南投市": "南投縣",
    "雲林": "雲林縣", "雲": "雲林縣", "林": "雲林縣", "雲縣": "雲林縣", "林縣": "雲林縣", "雲林市": "雲林縣",
    "屏東": "屏東縣", "屏": "屏東縣", "屏縣": "屏東縣", "屏東市": "屏東縣", "琉球嶼": "屏東縣", "小琉球": "屏東縣", "琉球": "屏東縣",
    "宜蘭": "宜蘭縣", "宜": "宜蘭縣", "蘭": "宜蘭縣", "宜縣": "宜蘭縣", "蘭縣": "宜蘭縣", "宜蘭市": "宜蘭縣", "龜山島": "宜蘭縣",
    "花蓮": "花蓮縣", "花": "花蓮縣", "蓮": "花蓮縣", "花縣": "花蓮縣", "蓮縣": "花蓮縣", "花蓮市": "花蓮縣",
    "台東": "臺東縣", "台東縣": "臺東縣", "台東市": "臺東市", "綠島": "臺東縣", "綠鳥": "臺東縣", "蘭嶼": "臺東縣",
    "澎湖": "澎湖縣", "澎": "澎湖縣", "湖": "澎湖縣", "澎縣": "澎湖縣", "湖縣": "澎湖縣", "澎湖市": "澎湖縣",
    "金門": "金門縣", "金": "金門縣", "門": "金門縣", "金縣": "金門縣", "門縣": "金門縣", "金門市": "金門縣",
    "連江": "連江縣", "連江市": "連江縣", "馬祖": "連江縣", "馬縣": "連江縣", "祖縣": "連江縣", "連": "連江縣", "江": "連江縣", "連縣": "連江縣"
}

def process_query(city_input, location_names, all_videos, movie_poster_urls, recommend_music, loaded_weather_codes):
    """處理天氣查詢和音樂/電影推薦的邏輯。"""
    reset_recommendation_states()

    if not city_input:
        st.session_state.result_text = "請輸入縣市名稱或天氣關鍵字！"
        return

    matched_city = None

    if city_input in MANUAL_CORRECTIONS:
        matched_city = MANUAL_CORRECTIONS[city_input]
    elif city_input in location_names:
        matched_city = city_input

    if matched_city:
        weather_data_raw = get_weather_data(matched_city)

        if weather_data_raw and weather_data_raw.get("status") == "success":
            weather_desc = weather_data_raw["description"]
            st.session_state.result_text = weather_data_raw["display_text"]

            # --- 天氣圖片邏輯：簡化處理 ---
            weather_code = None
            
            # 因為您的 CSV 總是匹配，我們可以這樣簡化獲取 weather_code
            for csv_desc, code in loaded_weather_codes.items():
                if weather_desc == csv_desc: # 精準匹配 weather_desc 到 CSV 中的中文描述
                    weather_code = code
                    break
            
            if weather_code is None: # 如果直接精準匹配沒有找到，可以嘗試模糊匹配作為備用
                highest_score = -1
                for csv_desc, code in loaded_weather_codes.items():
                    score = fuzz.ratio(weather_desc.lower(), csv_desc.lower())
                    if score > highest_score:
                        highest_score = score
                        weather_code = code # 取分數最高的 code

            if weather_code: # 確保找到了 weather_code
                found_image_path = get_image_path_or_default(WEATHER_IMAGES_DIR, weather_code)

                if found_image_path:
                    st.session_state.recommended_weather_image_html = load_local_image_as_base64(found_image_path, width=70)
                    # 簡化 caption：直接顯示天氣描述
                    st.session_state.weather_image_caption_desc = weather_desc
                else:
                    st.session_state.recommended_weather_image_html = None
                    st.session_state.weather_image_caption_desc = f"天氣：{weather_desc} (無圖片可用)"
            else:
                st.session_state.recommended_weather_image_html = None
                st.session_state.weather_image_caption_desc = f"天氣：{weather_desc} (無匹配代碼或圖片可用)"


            # --- 原有的音樂推薦邏輯 (保持不變) ---
            if recommend_music:
                music_text, youtube_id = find_and_recommend_music(weather_desc, all_videos)
                st.session_state.result_text += f"\n\n{music_text}"
                st.session_state.recommended_youtube_id = youtube_id
        else:
            st.session_state.result_text = weather_data_raw.get('display_text', f"抱歉，無法獲取 **{matched_city}** 的天氣資料。請檢查輸入或稍後再試。")
            # 如果天氣 API 失敗，嘗試顯示預設圖片
            default_image_path = get_image_path_or_default(WEATHER_IMAGES_DIR, "default") # 嘗試獲取預設圖
            if default_image_path:
                st.session_state.recommended_weather_image_html = load_local_image_as_base64(default_image_path, width=70)
                st.session_state.weather_image_caption_desc = f"無法取得 {matched_city} 天氣資料" # 移除預設圖片括號
            else:
                st.session_state.recommended_weather_image_html = None
                st.session_state.weather_image_caption_desc = f"無法取得 {matched_city} 天氣資料 (無圖片可用)"
    else:
        # 如果沒有匹配到縣市，直接根據輸入作為天氣描述推薦音樂
        weather_desc = city_input
        music_text, youtube_id = random_music_recommendation(all_videos) # 這裡改為隨機推薦，因為輸入不是縣市也不是天氣描述
        st.session_state.result_text = music_text
        st.session_state.recommended_youtube_id = youtube_id
        # 無天氣圖片
        st.session_state.recommended_weather_image_html = None
        st.session_state.weather_image_caption_desc = None

# --- Streamlit 應用程式主體 ---
def main():
    st.set_page_config(
        page_title="天氣心情點播網",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    # 加入背景圖片
    set_background("background.jpg")
    
    # 數據初始化
    location_names = get_location_names()
    all_videos = initialize_videos(EXCEL_FILE_PATH)
    movie_poster_urls = get_movie_poster_urls()
    loaded_weather_codes = load_weather_codes(WEATHER_CODES_FILE_PATH)

    # 集中化 Session State 初始化
    if 'initialized' not in st.session_state:
        st.session_state.result_text = ""
        st.session_state.recommended_youtube_id = None
        st.session_state.recommended_image_url = None
        st.session_state.recommended_music_original_indices = set()
        st.session_state.recommended_movie_indices = set() # 改用 set 更高效
        st.session_state.recommended_weather_image_html = None # 現在存儲 HTML 字串
        st.session_state.weather_image_caption_desc = None
        st.session_state.initialized = True # 標記為已初始化

    # --- 左側操作區 (使用 st.sidebar) ---
    with st.sidebar:

        city_input = st.text_input(
            "請輸入縣市或天氣：",
            placeholder="例如：臺北市 或 晴",
            key="sidebar_city_text_input"
        )

        if st.button("查詢天氣", key="sidebar_btn_query_weather", use_container_width=True):
            # 調用集中重置函數
            # reset_recommendation_states() # process_query 內部會調用，這裡可以不重複調用
            process_query(city_input, location_names, all_videos, movie_poster_urls,
                          recommend_music=False, loaded_weather_codes=loaded_weather_codes)

        if st.button("查詢天氣並推薦音樂", key="sidebar_btn_query_music", use_container_width=True):
            # 調用集中重置函數
            # reset_recommendation_states() # process_query 內部會調用，這裡可以不重複調用
            process_query(city_input, location_names, all_videos, movie_poster_urls,
                          recommend_music=True, loaded_weather_codes=loaded_weather_codes)

        if st.button("隨機音樂推薦", key="sidebar_btn_random_music", use_container_width=True):
            reset_recommendation_states() # 隨機推薦前，重置上次查詢或推薦的結果
            text_result, youtube_id = random_music_recommendation(all_videos)
            st.session_state.result_text = text_result
            st.session_state.recommended_youtube_id = youtube_id
            # 其他狀態已在 reset_recommendation_states() 中重置

        if st.button("隨機電影推薦", key="sidebar_btn_random_movie", use_container_width=True):
            reset_recommendation_states() # 隨機推薦前，重置上次查詢或推薦的結果
            display_name, poster_url, remaining = random_movie_recommendation(movie_poster_urls)
            if poster_url:
                st.session_state.result_text = f"為您推薦電影：**{display_name}**"
                st.session_state.recommended_image_url = poster_url
            else:
                st.session_state.result_text = display_name
            # 其他狀態已在 reset_recommendation_states() 中重置

        st.markdown("---")
        st.caption("Powered by [Streamlit](https://streamlit.io/)")
        st.caption("Copyright© Santana")
        st.caption("if you think I'm fine")
        st.caption("you can hire")

    # --- 主頁面顯示區 ---
    # 欄位比例調整為 [0.6, 0.1, 0.3] (標題, 圖片, 空白)
    # 將 st.subheader 替換為 st.title，以符合原意，但注意字體會較大
    title_col, image_col, empty_col = st.columns([0.5, 0.1, 0.4])

    with title_col:
        st.subheader("✧ 天氣心情點播網 ✧") # 保持 subheader，字體較為適中

    with image_col:
        # 顯示天氣圖片：現在檢查的是 HTML 內容
        if 'recommended_weather_image_html' in st.session_state and st.session_state.recommended_weather_image_html:
            # 直接渲染 Base64 編碼的 HTML 圖片
            st.markdown(st.session_state.recommended_weather_image_html, unsafe_allow_html=True)
            if st.session_state.weather_image_caption_desc:
                st.caption(st.session_state.weather_image_caption_desc)
        else:
            st.empty() # 如果沒有圖片，保持為空
           
    with empty_col:
        st.empty() # 保持此欄位為空，實現30%的空白

    # 顯示結果文字
    if 'result_text' in st.session_state and st.session_state.result_text:
        st.info(st.session_state.result_text)
    else:
        st.info("試試左邊功能吧！")

    st.markdown("---") # 在這個區塊下方加上分隔線

    # --- 影片推薦顯示區塊 (保持不變，但YouTube URL格式調整) ---
    if 'recommended_youtube_id' in st.session_state and st.session_state.recommended_youtube_id:
        st.subheader("♪ 音樂推薦 ♪ ")

        yt_col_left, yt_video_col, yt_col_right = st.columns([0.25, 0.5, 0.25])

        with yt_video_col:
            # 確保 Streamlit st.video 可以正確解析此連結，使用標準 v=ID 格式通常更穩妥
            # 原來的 https://www.youtube.com/watch?v={id} 格式可能在 Streamlit Cloud 上有問題
            # 最標準的嵌入連結通常是 https://www.youtube.com/embed/{id}
            st.video(f"https://www.youtube.com/watch?v={st.session_state.recommended_youtube_id}", format="video/mp4", start_time=0, loop=False, autoplay=False)
            st.caption(f"上方為推薦的 YouTube 影片。ID: {st.session_state.recommended_youtube_id}")

    # --- 電影海報推薦顯示區塊 (保持不變) ---
    elif 'recommended_image_url' in st.session_state and st.session_state.recommended_image_url:
        st.subheader("🎞️ 電影推薦")

        movie_col_left, movie_poster_col, movie_col_right = st.columns([0.4, 0.2, 0.4])

        with movie_poster_col:
            st.image(st.session_state.recommended_image_url, caption="推薦電影海報", use_container_width=True)

    st.markdown("<br><br>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()