# -*- coding: utf-8 -*-
import json
import re
import time
import random
import csv
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from urllib.parse import quote

# ====================== 配置区 ======================
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'db': '',
    'charset': 'utf8mb4'
}

CITY_CODES = {'北京': '530', '上海': '538', '广州': '763', '深圳': '765', '杭州': '653', '合肥': '664'}
Qwen_API_KEY = ""
Qwen_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
Qwen_MODEL_NAME = "qwen-"
CSV_FILENAME = "job_analysis_results_demo.csv"
SCRAPED_URLS = set()
CONFIG_PATH = "wantjob_pub.csv"
PROGRESS_FILE = "scrape_progress_pub.json"  # 进度记录文件

#quchongluoji
def normalize_zhilian_url(url):
    """标准化智联招聘URL，用于去重，更加可靠"""
    if not url:
        return ""
    # 去掉所有查询参数、末尾斜杠，并统一格式
    url = re.sub(r'\?.*$', '', url)      # 移除 ? 后面的参数
    url = re.sub(r'/$', '', url)         # 移除末尾 /
    # 统一成常见的 jobdetail 格式
    url = url.replace('/job/', '/jobdetail/')
    return url.strip()


def load_progress():
    """读取爬虫页码进度"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_progress(keyword, city, page_num,item_index=0):
    """更新当前任务的页码进度"""
    progress = load_progress()
    key = f"{keyword}_{city}"
    progress[key] = {
        "page_num": page_num,
        "item_index": item_index
    }
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=4)

def load_scraped_urls(filename=CSV_FILENAME):
    """重构后的读取函数：确保历史记录被标准化以用于去重"""
    urls = set()
    if not os.path.exists(filename):
        print("ℹ️ 未找到历史CSV文件，从头开始爬取")
        return urls
    try:
        with open(filename, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 兼容你代码中可能出现的“智联网址”或“job_url”键名
                url = row.get("智联网址") or row.get("job_url")
                if url:
                    urls.add(normalize_zhilian_url(url))
        print(f"✅ 已加载历史岗位 {len(urls)} 条（断点续爬模式）")
        return urls
    except Exception as e:
        print(f"⚠️ 读取历史CSV失败: {e}")
        return urls


def get_driver():
    """初始化浏览器配置，规避反爬检测"""
    # USER_AGENTS = [
    #     'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    #     'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36',
    # ]
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # 请确保此处路径正确
    driver = webdriver.Chrome(service=Service("D://chromedriver-win64//chromedriver.exe"), options=options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    })
    return driver


def extract_and_parse_job_data(driver):
    """正则提取详情页数据，支持对列表型字段（如skillLabel）的解析与清洗"""
    try:
        script_elements = driver.find_elements(By.XPATH, "//script[contains(text(), '__INITIAL_STATE__')]")
        if not script_elements:
            return None

        script_text = script_elements[0].get_attribute("innerHTML") or script_elements[0].get_attribute("textContent")

        # 定义需要提取的字段及其在网页源码 JSON 中的 key
        keys_to_extract = {
            "岗位名称": "positionName",
            "薪资": "salary",
            "岗位概述": "jobDesc",
            "公司名称": "companyName",
            "公司行业": "industryNameLevel",
            "公司规模": "companySize",
            "技能标签": "skillLabel",
            "公司简介": "companyDescription",
            "学历要求": "education",
            "经验要求": "positionWorkingExp",
            "工作地点": "workAddress",
            "工作城市": "positionWorkCity",
            "工作城市行政区": "positionCityDistrict",
            "岗位发布时间": "positionPublishTime",
            "招聘人数": "recruitNumber",
            "工作类型": "workType",
        }

        job_info = {}
        for info_key, json_key in keys_to_extract.items():
            # 优化正则：增加对 [ ... ] 列表格式的匹配支持
            pattern = rf'"{json_key}"\s*:\s*(\[.*?\]|"(.*?)"|([^,{{}}]+))'
            match = re.search(pattern, script_text, re.DOTALL)

            if match:
                raw_val = match.group(1).strip()
                # 1. 处理列表型数据（如 ["Python","Vue"]）
                if raw_val.startswith('['):
                    try:
                        val_list = json.loads(raw_val)
                        if isinstance(val_list, list):
                            # 数据清洗：去重、去空，并用中文逗号连接
                            cleaned_list = [str(item).strip() for item in val_list if item]
                            job_info[info_key] = "，".join(cleaned_list)
                        else:
                            job_info[info_key] = raw_val
                    except Exception:
                        job_info[info_key] = raw_val
                else:
                    # 2. 处理普通字符串或数值型数据
                    val = match.group(2) if match.group(2) is not None else match.group(3)
                    job_info[info_key] = val.strip() if val else None
            else:
                job_info[info_key] = None
        return job_info
    except Exception as e:
        print(f"❌ 数据提取失败: {e}")
    return None


def analyze_with_qwen(job_info):
    """利用 Qwen 模型进行岗位要求分析及岗位描述总结"""
    prompt = f"""
        你是一位专业的招聘数据分析师。请分析以下职位信息，并严格按照下方"输出格式"提供分析结果。

        ### 参考示例
        输入：岗位名称: Python后端工程师; 技能标签: Python,Flask,SQLAlchemy,Pandas; 原始描述: 负责后端API开发...
        输出：
        【岗位总结】: 负责后端服务开发与维护，处理业务逻辑与数据交互。
        【学习顺序】: Python → Flask → SQLAlchemy → Pandas → RESTful API → 数据库设计

        ### 待分析内容
        岗位名称: {job_info.get('岗位名称', '')}
        经验要求: {job_info.get('经验要求', '')}
        公司规模: {job_info.get('公司规模', '')}
        技能标签: {job_info.get('技能标签', '')}
        原始描述: {job_info.get('岗位概述', '')}

        任务：
        请严格按照以下格式提供分析（不要包含任何前言或多余说明）：
        【岗位总结】: (请凝练总结该岗位的核心职责。若原文有分点，请保持简明的有序列表 1. 2. 3. ...形式，并且写完一个点就换行，中间不要有空行。最多不超过10个点。)
        【学习顺序】: (基于技能标签，用 " → " 连接简练的知识点，体现从基础到进阶的逻辑，例如：Python → Flask → SQLAlchemy → Pandas → RESTful API → 数据库设计)
    """

    headers = {"Authorization": f"Bearer {Qwen_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": Qwen_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "parameters": {"enable_thinking": False}
    }
    # print("test：正在使用的请求参数：", data)

    try:
        response = requests.post(Qwen_API_URL, headers=headers, json=data)

        # 检查HTTP状态码
        if response.status_code != 200:
            print(f"❌ API 请求失败，状态码: {response.status_code}, 响应: {response.text}")
            return {"岗位总结": "分析失败", "学习顺序": f"API请求失败: {response.status_code}"}

        response_json = response.json()

        # 检查是否有错误信息
        if "error" in response_json:
            print(f"❌ API 返回错误: {response_json['error']}")
            return {"岗位总结": "分析失败", "学习顺序": f"API错误: {response_json['error'].get('message', '未知错误')}"}

        # 解析响应内容
        choices = response_json.get("choices", [])
        if not choices:
            print(f"❌ API 响应中没有 choices 字段: {response_json}")
            return {"岗位总结": "分析失败", "学习顺序": "API响应格式异常"}

        message_content = choices[0].get("message", {}).get("content", "")
        if not message_content:
            print(f"❌ API 响应中没有消息内容: {response_json}")
            return {"岗位总结": "分析失败", "学习顺序": "API返回内容为空"}

        print(f"🔭 API 响应内容: {message_content[:40]}...")  # 打印部分内容用于调试

        # --- 前面提取逻辑保持不变 ---
        summary_match = re.search(r"【岗位总结】[：:]\s*(.*?)(?=【|$)", message_content, re.S)
        study_path_match = re.search(r"【学习顺序】[：:]\s*(.*?)(?=【|$)", message_content, re.S)

        # 这里提取出字符串
        summary = summary_match.group(1).strip() if summary_match else "未提取"
        # 如果正则没匹配到，尝试按行查找关键字,zengjia Rubust
        if summary == "未提取":
            for line in message_content.split('\n'):
                if "岗位总结" in line:
                    summary = line.split(':', 1)[-1].split('：', 1)[-1].strip()
                    break
        study_path = study_path_match.group(1).strip() if study_path_match else "未提取"

        # --- 修改 return 部分，直接返回已提取的字符串 ---
        return {
            "岗位总结": summary,
            "学习顺序": study_path
        }

    except Exception as e:
        print(f"❌ Qwen分析过程中发生错误: {e}")
        return {"岗位总结": "分析失败", "学习顺序": f"错误: {str(e)}"}


def save_to_csv(data_list, filename=CSV_FILENAME):
    """实时追加数据到 CSV 文件，并确保列名为“智联网址”"""
    if not data_list:
        return

    processed_data_list = []
    for data in data_list:
        processed_data = {
            "岗位名称": data.get("岗位名称"),
            "薪资": data.get("薪资"),
            "岗位概述": data.get("岗位概述"),
            "公司名称": data.get("公司名称"),
            "公司行业": data.get("公司行业"),
            "公司规模": data.get("公司规模"),
            "技能标签": data.get("技能标签"),
            "公司简介": data.get("公司简介"),
            "学历要求": data.get("学历要求"),
            "经验要求": data.get("经验要求"),
            "工作地点": data.get("工作地点"),
            "工作城市": data.get("工作城市"),
            "工作城市行政区": data.get("工作城市行政区"),
            "岗位发布时间": data.get("岗位发布时间"),
            "招聘人数": data.get("招聘人数"),
            "工作类型": data.get("工作类型"),
            "智联网址": normalize_zhilian_url(data.get("job_url") or data.get("智联网址") or ""),  # 关键：统一列名
            "学习顺序": data.get("学习顺序"),
        }
        processed_data_list.append(processed_data)

    fieldnames = [
        "岗位名称", "薪资", "岗位概述", "公司名称", "公司行业", "公司规模",
        "技能标签", "公司简介", "学历要求", "经验要求", "工作地点",
        "工作城市", "工作城市行政区", "岗位发布时间", "招聘人数",
        "工作类型", "智联网址", "学习顺序"
    ]

    file_exists = os.path.isfile(filename)
    try:
        with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(processed_data_list)
        # print(f"✅ 已追加 {len(processed_data_list)} 条记录到 {filename}")
    except Exception as e:
        print(f"❌ CSV 导出失败: {e}")


def scrape_zhilian(keyword, city_name='上海', max_pages=None):
    """
    重新组织后的爬取核心逻辑：
    1. 修复了翻页逻辑嵌套错误。
    2. 确保进入新页面时条目索引(item_index)清零。
    3. 严格遵循原有的输出变量与去重逻辑。
    """
    city_code = CITY_CODES.get(city_name, '538')
    driver = get_driver()

    # 1. 初始化/加载进度
    progress = load_progress()
    task_key = f"{keyword}_{city_name}"
    task_progress = progress.get(task_key, {"page_num": 1, "item_index": 0})

    # 如果读取到的 task_progress 是旧版的数字，做兼容处理
    if isinstance(task_progress, int):
        page_num = task_progress
        item_index = 0
    else:
        page_num = task_progress.get("page_num", 1)
        item_index = task_progress.get("item_index", 0)

    print(f"📌 任务 [{keyword}-{city_name}] 从第 {page_num} 页 第 {item_index} 项接续...")

    try:
        while True:
            # 2. 访问列表页
            target_url = f"https://www.zhaopin.com/sou/?jl={city_code}&kw={quote(keyword)}&p={page_num}"
            print(f"📡 正在访问 [{city_name}] - [{keyword}] 第 {page_num} 页...")
            driver.get(target_url)
            time.sleep(random.uniform(7.59, 8.94))

            # 3. 获取所有岗位链接（保持网页原始顺序，不使用 set）
            items = driver.find_elements(By.XPATH,
                                         "//div[contains(@class, 'jobinfo__top')]//a[contains(@href, 'jobdetail')]")
            job_urls = [i.get_attribute('href') for i in items if i.get_attribute('href')]

            if not job_urls:
                print(f"未检测到更多职位，{city_name} {keyword} 爬取结束。")
                break

            # 4. 遍历当前页的每一个岗位
            for current_index, url in enumerate(job_urls):
                # 精确跳过已爬取的索引项
                if current_index < item_index:
                    continue

                # 标准化去重检查
                normalized_url = normalize_zhilian_url(url)
                if normalized_url in SCRAPED_URLS:
                    print(f"⏩ 跳过已存在: {normalized_url}")
                    save_progress(keyword, city_name, page_num, current_index + 1)
                    continue

                try:
                    # 打开详情页
                    driver.execute_script(f"window.open('{url}');")
                    driver.switch_to.window(driver.window_handles[-1])
                    time.sleep(random.uniform(4.82, 5.56))

                    # 尝试关闭登录弹窗
                    try:
                        close_btn = driver.find_element(By.XPATH,
                                                        "//div[contains(@class,'login-popups')]//button[contains(@class,'a-dialog__close')]")
                        close_btn.click()
                    except:
                        pass

                    # 5. 提取与 AI 分析
                    job_data = extract_and_parse_job_data(driver)
                    if job_data:
                        actual_url = driver.current_url
                        job_data["job_url"] = actual_url  # 保持内部 job_url 命名

                        # 调用 AI 分析
                        analysis_results = analyze_with_qwen(job_data)
                        ai_summary = analysis_results.get("岗位总结", "")

                        if ai_summary and ai_summary not in ["未提取", "分析失败"]:
                            job_data["岗位概述"] = ai_summary  # 替换原始描述
                            job_data["学习顺序"] = analysis_results.get("学习顺序", "未提取")
                        else:
                            print("❌岗位概述和学习顺序出现未提取错误！！💀")

                        # 6. 保存并加入已爬集合
                        save_to_csv([job_data])
                        SCRAPED_URLS.add(normalize_zhilian_url(actual_url))
                        print(
                            f"✅ [P{page_num}-I{current_index}] 已存入: {job_data.get('岗位名称')} | {job_data.get('公司名称')}")

                    # 关闭详情页回到列表页
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                    # 7. 每成功一条，更新进度为“下一条”
                    save_progress(keyword, city_name, page_num, current_index + 1)

                except Exception as inner_e:
                    print(f"💔 详情页抓取失败: {inner_e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])

            # 8. 当前页遍历结束，翻页逻辑（注意：必须在 for 循环外面）
            page_num += 1
            item_index = 0  # 进入新页面，索引重置为 0
            save_progress(keyword, city_name, page_num, 0)
            print(f"⏭️ 第 {page_num - 1} 页处理完毕，即将进入第 {page_num} 页...")

    finally:
        driver.quit()


def load_tasks(config_path=CONFIG_PATH):
    """从 CSV 文件读取任务列表"""
    tasks = []
    if not os.path.exists(config_path):
        print(f"⚠️ 未找到 {config_path}，执行默认示例任务")
        return [{"keyword": "python", "city": "上海"}]
    try:
        with open(config_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("keyword") and row.get("city"):
                    tasks.append({"keyword": row["keyword"].strip(), "city": row["city"].strip()})
        return tasks
    except Exception as e:
        print(f"❌ 读取 CSV 任务文件失败: {e}")
        return []



if __name__ == "__main__":
    SCRAPED_URLS = load_scraped_urls()

    tasks = load_tasks()
    if not tasks:
        print("没有任务可执行，程序结束")
        exit()
    print(f"共加载 {len(tasks)} 个任务")

    for i, task in enumerate(tasks, 1):
        kw = task.get("keyword")
        city = task.get("city")
        print(f"\n===== 执行任务 {i}/{len(tasks)} : {kw} - {city} =====")
        scrape_zhilian(keyword=kw, city_name=city, max_pages=None)