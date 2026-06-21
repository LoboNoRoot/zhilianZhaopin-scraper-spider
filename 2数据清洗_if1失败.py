import pandas as pd
import dashscope
from dashscope import Generation
from http import HTTPStatus
import time
import re
from tqdm import tqdm

# ================= 配置区域 =================
# 1. 替换为你的 DashScope API Key
dashscope.api_key = "YOUR_DASHSCOPE_API_KEY"

# 2. 设置使用的模型
MODEL_NAME = "qwen-turbo"  # 或 "qwen-max"

# 3. 文件路径
INPUT_CSV = "job_analysis_results_demo.csv"
OUTPUT_CSV = "job_analysis_processed.csv"


# ===========================================

def call_qwen_api(prompt):
    """通用 Qwen API 调用函数"""
    try:
        response = Generation.call(
            model=MODEL_NAME,
            prompt=prompt,
            result_format='message'
        )
        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0].message.content.strip()
        else:
            print(f"API Error: {response.code} - {response.message}")
            return None
    except Exception as e:
        print(f"Exception during API call: {e}")
        return None


def process_analysis():
    print(f"正在读取文件: {INPUT_CSV}")
    # 读取原始数据
    try:
        df = pd.read_csv(INPUT_CSV)
    except FileNotFoundError:
        print(f"错误：找不到文件 {INPUT_CSV}")
        return

    # 检查必要的列是否存在
    if '岗位概述' not in df.columns:
        print("错误：CSV 文件中未找到 '岗位概述' 列")
        return

    print("开始调用 Qwen 进行 AI 分析...")

    # 使用 tqdm 显示进度
    for index, row in tqdm(df.iterrows(), total=len(df), desc="分析进度"):
        # 将当前行转为字典，方便 Prompt 模板引用
        job_info = row.to_dict()

        # 使用你指定的 Prompt 模板
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

        # 执行分析
        full_result = call_qwen_api(prompt)

        if full_result:
            # 解析输出内容
            # 使用正则提取 【岗位总结】 和 【学习顺序】 之后的内容
            summary_match = re.search(r'【岗位总结】:\s*(.*?)(?=【学习顺序】:|$)', full_result, re.DOTALL)
            path_match = re.search(r'【学习顺序】:\s*(.*)', full_result, re.DOTALL)

            if summary_match:
                # 替换原始“岗位概述”列
                df.at[index, '岗位概述'] = summary_match.group(1).strip()

            if path_match:
                # 替换/更新“学习顺序”列
                df.at[index, '学习顺序'] = path_match.group(1).strip()

        # 频率控制
        time.sleep(0.5)

    # 保存结果，使用 utf-8-sig 确保 Excel 打开不乱码
    df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
    print(f"\n处理完成！分析结果已直接替换原列，并保存至: {OUTPUT_CSV}")


if __name__ == "__main__":
    process_analysis()