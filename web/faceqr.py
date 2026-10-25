# -*- coding: utf-8 -*-
"""人脸采集二维码: 纯 requests 复现网页端人脸弹窗的二维码获取与状态轮询.

流程(逆向自 studentstudy 页面的 getQRCodeURLShow1/getstatus1):
1. 章节树页(studentcourse)携带页面级全局 enc, 用于拼接 studentstudy 页 URL
2. studentstudy 页内嵌 /qr/produce 的 uuid/enc 与隐藏字段(videoJobId 等)
3. GET /mooc-ans/qr/produce -> {url, qrcContentEnc, newUuid, newEnc}
4. 二维码图片 = /mooc-ans/phone/course/qrc?content=<url>&enc=<qrcContentEnc>
5. GET /mooc-ans/qr/getqrstatus 轮询扫码状态, HTTP 202 表示验证完成需刷新
"""
import base64
import re

MOOC1 = "https://mooc1.chaoxing.com"

_HIDDEN_IDS = [
    "videoJobId", "chapterVideoObjectId", "collectionTime", "videoRandomCollectTime",
    "mid", "chapterIdid", "fcclazzIdQr", "fccourseIdQr", "fccpiQr",
    "faceBlockEnterVideoQr",
]


def parse_tree_enc(tree_html: str) -> str | None:
    """从章节树页提取页面级全局 enc(studentstudy URL 使用)."""
    match = re.search(r'var\s+enc\s*=\s*"([0-9a-f]{32})"', tree_html)
    return match.group(1) if match else None


def parse_hidden(html: str, field_id: str) -> str:
    """提取隐藏 input 的 value, 兼容 id/value 属性顺序."""
    for pattern in (
        rf'id="{field_id}"[^>]*value="([^"]*)"',
        rf'value="([^"]*)"[^>]*id="{field_id}"',
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


def has_face_demand(study_html: str) -> bool:
    """studentstudy 页是否存在待完成的人脸采集(videoCaptureGetQrStatuse=1)."""
    return bool(re.search(r'id="videoCaptureGetQrStatuse"[^>]*value="1"', study_html))


def has_face_markers(study_html: str) -> bool:
    """studentstudy 页是否携带人脸抓拍相关标记(课程级配置信号).

    实测对照: 配置了人脸抓拍的课程所有章节页面均带这三者;
    未配置的章节页面字段为空且无弹窗模板.
    """
    if has_face_demand(study_html):
        return True
    if parse_hidden(study_html, "faceBlockEnterVideoQr") not in ("", None):
        return True
    return "faceCollectQrPopVideo" in study_html


def course_face_capture(session, course_id: str, clazz_id: str, cpi: str,
                        points: list, tree_enc: str) -> bool:
    """课程级人脸抓拍检测: 检查首个章节的 studentstudy 标记(2 个请求)."""
    if not points:
        return False
    study_html = fetch_study_html(session, course_id, clazz_id, cpi, points[0]["id"], tree_enc)
    return has_face_markers(study_html)


def parse_study_tokens(study_html: str) -> dict | None:
    """提取人脸二维码生成所需的页面令牌与上下文参数.

    注意: videoJobId/chapterVideoObjectId/mid 等字段在服务端渲染的 HTML 中为空,
    由网页 JS 从视频上下文动态填充; Python 侧需调用方用 get_job_list 的结果补全.
    """
    match = re.search(r"/qr/produce\?uuid=([\w-]+)&enc=(\w+)", study_html)
    if not match:
        return None
    tokens = {"produceUuid": match.group(1), "produceEnc": match.group(2)}
    for field in _HIDDEN_IDS:
        tokens[field] = parse_hidden(study_html, field)
    return tokens


def fill_tokens_from_job(tokens: dict, job: dict, chapter_id: str) -> dict:
    """用视频任务点数据补全服务端 HTML 中为空的字段(对应网页 JS 的填充行为)."""
    tokens["videoJobId"] = str(job.get("jobid", ""))
    tokens["chapterVideoObjectId"] = str(job.get("objectid", ""))
    tokens["collectionTime"] = tokens["collectionTime"] or "0"
    tokens["videoRandomCollectTime"] = tokens["videoRandomCollectTime"] or "0"
    tokens["mid"] = str(job.get("mid", "") or "")
    tokens["chapterIdid"] = str(chapter_id)
    return tokens


def check_face_demand(session, tree_enc: str, course_id: str, clazz_id: str, cpi: str,
                      points: list, chapter_title: str = "", limit: int = 10) -> tuple[bool, str]:
    """轻量检查: 章节是否存在待完成的人脸采集(用于区分人脸抓拍与风控冷却).

    优先检查标题匹配的章节(运行中被拦的章节), 找到即返回 (True, 章节标题).
    """
    ordered = points
    if chapter_title:
        hits = [p for p in points if chapter_title in p.get("title", "")]
        if hits:
            ordered = hits + [p for p in points if p not in hits]
    for point in ordered[:limit]:
        study_html = fetch_study_html(session, course_id, clazz_id, cpi, point["id"], tree_enc)
        if has_face_demand(study_html):
            return True, point.get("title", "")
    return False, ""


def fetch_study_html(session, course_id: str, clazz_id: str, cpi: str,
                     chapter_id: str, tree_enc: str) -> str:
    url = (
        f"{MOOC1}/mycourse/studentstudy?chapterId={chapter_id}&courseId={course_id}"
        f"&clazzid={clazz_id}&cpi={cpi}&enc={tree_enc}&mooc2=1&hidetype=0&fanyaVersion=0"
    )
    return session.get(url).text


def produce_face_qr(session, tokens: dict) -> dict:
    """调 /qr/produce 换取新二维码, 返回 {qr_base64, status_tokens}."""
    resp = session.get(
        f"{MOOC1}/mooc-ans/qr/produce",
        params={
            "uuid": tokens["produceUuid"],
            "enc": tokens["produceEnc"],
            "clazzid": tokens["fcclazzIdQr"],
            "videojobid": tokens["videoJobId"],
            "chaptervideoobjectid": tokens["chapterVideoObjectId"],
            "videoCollectTime": tokens["collectionTime"] or "0",
        },
    ).json()
    if not isinstance(resp, dict) or "url" not in resp:
        raise RuntimeError(f"二维码生成失败: {str(resp)[:120]}")

    # content 参数已是编码后的 URL, 手动拼接避免 requests 二次编码
    qr_url = f"{MOOC1}/mooc-ans/phone/course/qrc?content={resp['url']}&enc={resp.get('qrcContentEnc', '')}"
    image = session.get(qr_url).content
    return {
        "qr_base64": base64.b64encode(image).decode("ascii"),
        # getqrstatus 轮询所需(与网页端 getstatus1 的取值一一对应)
        "status_tokens": {
            "uuid": resp.get("newUuid", ""),
            "enc": resp.get("newEnc", ""),
            "clazzid": tokens["fcclazzIdQr"],
            "courseid": tokens["fccourseIdQr"],
            "cpi": tokens["fccpiQr"],
            "mid": tokens["mid"],
            "chapterId": tokens["chapterIdid"],
            "videoObjectId": tokens["chapterVideoObjectId"],
            "collectionTime": tokens["collectionTime"] or "0",
            "videoRandomCollectTime": tokens["videoRandomCollectTime"] or "0",
        },
    }


def poll_face_status(session, status_tokens: dict) -> dict:
    """轮询扫码状态: {done, status, code} — done=True 表示人脸验证完成."""
    resp = session.get(f"{MOOC1}/mooc-ans/qr/getqrstatus", params={
        "uuid": status_tokens.get("uuid", ""),
        "enc": status_tokens.get("enc", ""),
        "clazzid": status_tokens.get("clazzid", ""),
        "courseid": status_tokens.get("courseid", ""),
        "cpi": status_tokens.get("cpi", ""),
        "collectionTime": status_tokens.get("collectionTime", ""),
        "mid": status_tokens.get("mid", ""),
        "videoObjectId": status_tokens.get("videoObjectId", ""),
        "videoRandomCollectTime": status_tokens.get("videoRandomCollectTime", ""),
        "chapterId": status_tokens.get("chapterId", ""),
    })
    # 网页端逻辑: HTTP 202 -> reload(验证完成, 拦截解除)
    if resp.status_code == 202:
        return {"done": True, "status": 202, "code": None}
    try:
        data = resp.json()
    except ValueError:
        return {"done": False, "status": resp.status_code, "code": None}
    # status==0 继续等待; 其余按平台语义视为有结果
    return {"done": data.get("status") not in (0, None), "status": data.get("status"), "code": data.get("code")}
