#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财报下载脚本
支持下载比亚迪、中际旭创、宁德时代四家公司的财报
下载最近1年的年报、中报和季报
"""

import requests
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# 配置
DOWNLOAD_DIR = "data/financials/downloads"
TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 创建下载目录
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path

# 下载文件
def download_file(url, filepath, headers=None):
    """下载文件到指定路径"""
    try:
        h = HEADERS.copy()
        if headers:
            h.update(headers)
        response = requests.get(url, headers=h, timeout=TIMEOUT, stream=True)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  下载失败: {url}, 错误: {e}")
        return False

# ==================== 比亚迪 ====================
def download_byd():
    """下载比亚迪财报"""
    print("\n=== 开始下载比亚迪财报 ===")
    company_dir = ensure_dir(os.path.join(DOWNLOAD_DIR, "比亚迪"))
    
    # 比亚迪API端点 - 使用页面抓取的API
    api_url = "https://www.bydglobal.com/sites/REST/resources/v1/search/sites/BYD_CN/types/BydInvestorNotice/assets"
    params = {
        "fields": "name,id,createdby,updatedby,description,Title,publishTime,loadFile",
        "field:subtype:equals": "regualrReport",
        "orderBy": "publishTime:desc",
        "links": "next"
    }
    
    # 使用session保持cookie
    session = requests.Session()
    byd_headers = {
        **HEADERS,
        "Accept": "application/json;charset=utf-8",
        "Referer": "https://www.bydglobal.com/cn/Investor/InvestorAnnals.html",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    try:
        # 先访问主页面获取cookie
        print("  正在连接比亚迪官网...")
        main_page = session.get("https://www.bydglobal.com/cn/Investor/InvestorAnnals.html", headers=byd_headers, timeout=TIMEOUT)
        main_page.raise_for_status()
        
        # 获取API数据
        response = session.get(api_url, params=params, headers=byd_headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        if "items" not in data:
            print("  无法获取比亚迪财报列表")
            return
        
        print(f"  找到 {len(data['items'])} 条财报记录")
        
        current_year = datetime.now().year
        ten_years_ago = current_year - 1
        downloaded = 0
        
        for item in data["items"]:
            try:
                title = item.get("Title", "")
                pdf_id = item.get("id", "")
                publish_time = item.get("publishTime", {}).get("value", "")
                
                # 检查是否是最近10年的
                if publish_time:
                    year = int(publish_time[:4])
                    if year < ten_years_ago:
                        continue
                
                # 获取PDF下载链接
                pdf_info_url = f"https://www.bydglobal.com/sites/Satellite?c=BydInvestorNotice&d=&rendermode=preview&cid={pdf_id}&pagename=BYD_CN%2FBydInvestorNotice%2FInvestorLoad"
                pdf_response = session.get(pdf_info_url, headers={**byd_headers, "Accept": "application/json; charset=utf-8"}, timeout=TIMEOUT)
                
                if pdf_response.status_code == 200:
                    try:
                        pdf_data = pdf_response.json()
                        pdf_url = pdf_data.get("url", "")
                        if pdf_url:
                            # 构建完整URL
                            if pdf_url.startswith("/"):
                                pdf_url = f"https://www.bydglobal.com{pdf_url}"
                            
                            # 生成文件名
                            safe_title = re.sub(r'[\\/*?":<>|]', '_', title)
                            filename = f"{safe_title}.pdf"
                            filepath = os.path.join(company_dir, filename)
                            
                            if not os.path.exists(filepath):
                                print(f"  下载: {title}")
                                # 使用session下载PDF
                                pdf_download = session.get(pdf_url, headers=byd_headers, timeout=TIMEOUT, stream=True)
                                pdf_download.raise_for_status()
                                with open(filepath, 'wb') as f:
                                    for chunk in pdf_download.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                downloaded += 1
                                time.sleep(1)
                            else:
                                print(f"  已存在: {title}")
                    except Exception as e:
                        print(f"  处理PDF时出错: {e}")
                        continue
                        
            except Exception as e:
                print(f"  处理比亚迪财报时出错: {e}")
                continue
        
        print(f"  共下载 {downloaded} 个比亚迪财报文件")
                
    except Exception as e:
        print(f"  获取比亚迪财报列表失败: {e}")

# ==================== 中际旭创 ====================
def download_innolight():
    """下载中际旭创财报"""
    print("\n=== 开始下载中际旭创财报 ===")
    company_dir = ensure_dir(os.path.join(DOWNLOAD_DIR, "中际旭创"))
    
    base_url = "https://www.zj-innolight.com/index/index/inv2.html"
    page = 1
    downloaded_count = 0
    max_pages = 1  # 最多爬1页
    
    while page <= max_pages:
        try:
            if page == 1:
                url = base_url
            else:
                url = f"{base_url}?page={page}"
            
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找所有PDF链接
            pdf_links = soup.find_all('a', href=re.compile(r'.*\.(pdf|PDF)$'))
            
            if not pdf_links:
                break
            
            for link in pdf_links:
                try:
                    href = link.get('href', '')
                    if not href:
                        continue
                    
                    # 获取标题
                    title = link.get_text(strip=True)
                    if not title:
                        title = os.path.basename(href)
                    
                    # 构建完整URL
                    if href.startswith('/'):
                        pdf_url = f"https://www.zj-innolight.com{href}"
                    elif href.startswith('http'):
                        pdf_url = href
                    else:
                        pdf_url = f"https://www.zj-innolight.com/{href}"
                    
                    # 生成文件名
                    safe_title = re.sub(r'[\\/*?":<>|]', '_', title)
                    if not safe_title.endswith('.pdf'):
                        filename = f"{safe_title}.pdf"
                    else:
                        filename = safe_title
                    
                    filepath = os.path.join(company_dir, filename)
                    
                    if not os.path.exists(filepath):
                        print(f"  下载: {title}")
                        if download_file(pdf_url, filepath):
                            downloaded_count += 1
                        time.sleep(1)
                    else:
                        print(f"  已存在: {title}")
                        
                except Exception as e:
                    print(f"  处理中际旭创财报时出错: {e}")
                    continue
            
            page += 1
            time.sleep(2)
            
        except Exception as e:
            print(f"  获取中际旭创第{page}页失败: {e}")
            break
    
    print(f"  共下载 {downloaded_count} 个中际旭创财报文件")

# ==================== 宁德时代 ====================
def download_catl():
    """下载宁德时代财报"""
    print("\n=== 开始下载宁德时代财报 ===")
    company_dir = ensure_dir(os.path.join(DOWNLOAD_DIR, "宁德时代"))
    
    api_url = "https://www.catl.com/ajax/iRSerach"
    current_year = datetime.now().year
    downloaded_count = 0
    
    # 获取最近1年的财报
    for year in range(current_year, current_year - 1, -1):
        try:
            data = {
                "index": "1",
                "subtitle": "",
                "nodeIds": "regularnotice",
                "year": str(year),
                "docType": "",
                "text": "",
                "pageSize": "100"
            }
            
            headers = {
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.catl.com/inverelations/"
            }
            
            response = requests.post(api_url, data=data, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            result = response.json()
            
            if "data" in result and result["data"]:
                for item in result["data"]:
                    try:
                        title = item.get("title", "")
                        pdf_url = item.get("file", "")
                        
                        if pdf_url and title:
                            if pdf_url.startswith('/'):
                                pdf_url = f"https://www.catl.com{pdf_url}"
                            
                            safe_title = re.sub(r'[\\/*?":<>|]', '_', title)
                            filename = f"{safe_title}.pdf"
                            filepath = os.path.join(company_dir, filename)
                            
                            if not os.path.exists(filepath):
                                print(f"  下载: {title}")
                                if download_file(pdf_url, filepath):
                                    downloaded_count += 1
                                time.sleep(1)
                            else:
                                print(f"  已存在: {title}")
                                
                    except Exception as e:
                        print(f"  处理宁德时代财报时出错: {e}")
                        continue
                        
        except Exception as e:
            print(f"  获取宁德时代{year}年财报失败: {e}")
            continue
    
    print(f"  共下载 {downloaded_count} 个宁德时代财报文件")

# ==================== 主函数 ====================
def main():
    """主函数"""
    print("=" * 60)
    print("财报下载脚本")
    print("支持: 比亚迪、寒武纪、中际旭创、宁德时代")
    print("=" * 60)
    
    # 下载各公司财报
    download_byd()
    download_innolight()
    download_catl()
    
    print("\n" + "=" * 60)
    print("财报下载完成!")
    print(f"文件保存在: {os.path.abspath(DOWNLOAD_DIR)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
