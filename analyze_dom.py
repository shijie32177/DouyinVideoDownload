#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析抖音收藏夹页面的 DOM 滚动容器结构
"""

import json
import time
import os
from DrissionPage import ChromiumPage, ChromiumOptions

COOKIE_FILE = os.path.expanduser("~/.douyin_tool_cookie")
PROFILE_DIR = os.path.expanduser("~/.douyin_drission_profile")
DEBUG_PORT = 9334
TARGET_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"

SCROLL_JS = """(function(){
    var results = [];
    var all = document.querySelectorAll('*');
    for(var i=0; i<all.length; i++){
        var el = all[i];
        if(el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 50){
            results.push({
                tag: el.tagName,
                cls: el.className.substring(0,80),
                sh: el.scrollHeight,
                ch: el.clientHeight,
                st: el.scrollTop
            });
        }
    }
    results.sort(function(a,b){return b.sh-a.sh;});
    return JSON.stringify(results.slice(0,15));
})()"""


def load_cookies(filepath):
    """读取 cookie 文件，支持多种格式"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # 尝试 JSON 数组格式
    if content.startswith("["):
        cookies = json.loads(content)
        return cookies

    # 尝试单行 JSON 对象
    if content.startswith("{"):
        cookie_obj = json.loads(content)
        cookies = []
        for name, value in cookie_obj.items():
            cookies.append({"name": name, "value": value, "domain": ".douyin.com"})
        return cookies

    # 单行 name=value; name2=value2 格式（浏览器 cookie 字符串）
    if "=" in content and "\n" not in content:
        cookies = []
        for part in content.split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                name = name.strip()
                value = value.strip()
                if name:
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": ".douyin.com",
                        "path": "/",
                    })
        return cookies

    # Netscape/文本格式: domain\tpath\tsecure\texpiry\tname\tvalue
    cookies = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies.append({
                "domain": parts[0],
                "path": parts[2] if len(parts) > 2 else "/",
                "secure": parts[3].upper() == "TRUE" if len(parts) > 3 else False,
                "name": parts[5],
                "value": parts[6],
            })
    return cookies


def safe_json_parse(result):
    """DrissionPage run_js 可能返回 Python list/dict 或 JSON 字符串"""
    if result is None:
        return None
    if isinstance(result, (list, dict)):
        return result
    if isinstance(result, str):
        return json.loads(result)
    return result


def print_scroll_results(label, result_json):
    print(f"\n=== {label} ===")
    if result_json is None:
        print("  JS 返回 None（页面可能未完全加载）")
        return
    try:
        items = safe_json_parse(result_json)
        if items is None:
            print("  结果为 None")
            return
        for i, item in enumerate(items):
            print(f"  [{i+1:2d}] tag={item['tag']:<10} sh={item['sh']:6d} ch={item['ch']:5d} st={item['st']:5d}  cls={item['cls']}")
    except Exception as e:
        print(f"  解析失败: {e}")
        print(f"  原始: {str(result_json)[:500]}")


def main():
    print("[1] 启动 Chrome...")
    co = ChromiumOptions()
    co.set_local_port(DEBUG_PORT)
    co.set_user_data_path(PROFILE_DIR)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-blink-features=AutomationControlled")
    # 不尝试连接已存在的浏览器，直接启动新的
    co.set_argument("--remote-debugging-port=" + str(DEBUG_PORT))

    try:
        page = ChromiumPage(co)
    except Exception as e:
        print(f"  启动失败: {e}")
        print("  尝试不指定 profile 目录...")
        co2 = ChromiumOptions()
        co2.set_local_port(DEBUG_PORT)
        co2.set_argument("--no-sandbox")
        co2.set_argument("--remote-debugging-port=" + str(DEBUG_PORT))
        page = ChromiumPage(co2)

    # 先导航到抖音主页以便注入 cookie
    print("[2] 导航到抖音主页注入 cookie...")
    page.get("https://www.douyin.com")
    page.wait.doc_loaded()
    time.sleep(2)

    # 注入 cookie
    print("[3] 注入 cookie...")
    try:
        cookies = load_cookies(COOKIE_FILE)
        print(f"  读取到 {len(cookies)} 个 cookie")
        for ck in cookies:
            try:
                # DrissionPage 4.x: set_cookies 接受单个 cookie 字典
                page.set.cookies(ck)
            except Exception as e:
                # 部分 cookie 可能因域名不匹配而失败，忽略
                pass
    except Exception as e:
        print(f"  cookie 加载失败: {e}")
        return

    # 导航到目标页面
    print(f"[4] 导航到: {TARGET_URL}")
    page.get(TARGET_URL)
    page.wait.doc_loaded()
    print("  doc_loaded 完成，等待 3s 让 JS 渲染...")
    time.sleep(3)
    print(f"  当前 URL: {page.url}")
    print(f"  页面标题: {page.title}")

    # 第一次运行滚动容器 JS
    print("[5] 运行滚动容器分析 JS（初始状态）...")
    result1 = page.run_js(SCROLL_JS, as_expr=True)
    print_scroll_results("初始可滚动容器（按 scrollHeight 降序）", result1)

    # 查找含"共"+"作品"的 li 元素
    print("\n[6] 查找含'共'+'作品'的 li 元素...")
    find_li_js = """(function(){
        var lis = document.querySelectorAll('li');
        var found = [];
        for(var i=0; i<lis.length; i++){
            var txt = lis[i].innerText || lis[i].textContent;
            if(txt.indexOf('共') !== -1 && txt.indexOf('作品') !== -1){
                found.push({
                    idx: i,
                    text: txt.substring(0, 100).replace(/\\n/g, ' ').trim(),
                    cls: lis[i].className.substring(0, 80)
                });
            }
        }
        return JSON.stringify(found.slice(0, 5));
    })()"""

    li_result = page.run_js(find_li_js, as_expr=True)
    try:
        lis = safe_json_parse(li_result) or []
        if lis:
            print(f"  找到 {len(lis)} 个含'共'+'作品'的 li：")
            for item in lis:
                print(f"    [idx={item['idx']}] cls={item['cls']}")
                print(f"           text={item['text']}")
        else:
            print("  未找到含'共'+'作品'的 li")
    except Exception as e:
        print(f"  解析失败: {e}, 原始: {str(li_result)[:300]}")
        lis = []

    # 点击第一个含"共"+"作品"的 li
    if lis:
        first_idx = lis[0]['idx']
        print(f"\n[7] 点击第一个 li (index={first_idx})...")
        click_js = f"""(function(){{
            var lis = document.querySelectorAll('li');
            var li = lis[{first_idx}];
            if(li){{
                li.click();
                return 'clicked: ' + (li.innerText || li.textContent).substring(0, 50);
            }}
            return 'not found';
        }})()"""
        click_result = page.run_js(click_js, as_expr=True)
        print(f"  点击结果: {click_result}")
        print("  等待 2s...")
        time.sleep(2)
    else:
        print("\n[7] 无可点击的 li，跳过点击步骤")

    # 点击后再次运行滚动容器 JS
    print("[8] 运行滚动容器分析 JS（点击后）...")
    result2 = page.run_js(SCROLL_JS, as_expr=True)
    print_scroll_results("点击后可滚动容器（按 scrollHeight 降序）", result2)

    # 再次查找含"共"+"作品"的 li 文字（前5个）
    print("\n[9] 点击后，前5个含'共'+'作品'的 li 文字：")
    li_result2 = page.run_js(find_li_js, as_expr=True)
    try:
        lis2 = safe_json_parse(li_result2) or []
        if lis2:
            for item in lis2:
                print(f"  [{item['idx']}] {item['text']}  |  cls={item['cls']}")
        else:
            print("  未找到含'共'+'作品'的 li")
    except Exception as e:
        print(f"  解析失败: {e}")

    # 额外分析：查找左侧收藏夹列表和右侧视频列表的关键容器
    print("\n[10] 深度分析：查找关键 DOM 容器...")
    deep_js = """(function(){
        var info = {};

        // 找所有 ul 和 ol（可能是列表容器）
        var lists = document.querySelectorAll('ul, ol');
        var listInfo = [];
        for(var i=0; i<lists.length; i++){
            var el = lists[i];
            var children = el.children.length;
            if(children > 0){
                listInfo.push({
                    tag: el.tagName,
                    cls: el.className.substring(0, 80),
                    children: children,
                    sh: el.scrollHeight,
                    ch: el.clientHeight
                });
            }
        }
        listInfo.sort(function(a,b){ return b.children - a.children; });
        info.lists = listInfo.slice(0, 10);

        // 找包含 favorite/collect/folder 相关 class 的元素
        var all = document.querySelectorAll('*');
        var favElements = [];
        var keywords = ['favorite', 'collect', 'folder', 'playlist', 'fav', 'bookmark'];
        for(var i=0; i<all.length; i++){
            var cls = all[i].className || '';
            if(typeof cls === 'string'){
                for(var k=0; k<keywords.length; k++){
                    if(cls.toLowerCase().indexOf(keywords[k]) !== -1){
                        favElements.push({
                            tag: all[i].tagName,
                            cls: cls.substring(0, 80),
                            sh: all[i].scrollHeight,
                            ch: all[i].clientHeight
                        });
                        break;
                    }
                }
            }
        }
        info.favElements = favElements.slice(0, 15);

        return JSON.stringify(info);
    })()"""

    deep_result = page.run_js(deep_js, as_expr=True)
    try:
        deep = safe_json_parse(deep_result) or {}

        print("\n  -- 子元素最多的列表容器（ul/ol）--")
        for item in deep.get("lists", []):
            print(f"    {item['tag']} children={item['children']:3d} sh={item['sh']:6d} ch={item['ch']:5d}  cls={item['cls']}")

        print("\n  -- 含 favorite/collect/folder 等关键词的元素 --")
        for item in deep.get("favElements", []):
            print(f"    {item['tag']} sh={item['sh']:6d} ch={item['ch']:5d}  cls={item['cls']}")
    except Exception as e:
        print(f"  解析失败: {e}")

    print("\n[完成] DOM 分析结束")


if __name__ == "__main__":
    main()
