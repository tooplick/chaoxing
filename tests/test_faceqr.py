# -*- coding: utf-8 -*-
"""web.faceqr 解析函数单元测试(基于真实页面结构的人工样例)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.faceqr import (  # noqa: E402
    fill_tokens_from_job,
    has_face_demand,
    has_face_markers,
    parse_hidden,
    parse_study_tokens,
    parse_tree_enc,
)

TREE_HTML = """
<script>
    var mooc1Domain = "https://mooc1.chaoxing.com";
    var enc = "60f046f94cbf2eb5fc76ba2d0aedd470";
    var cpi = 419533201;
</script>
"""

STUDY_HTML = """
<input type="hidden" id="videoJobId" value=""/>
<input type="hidden" value="d642d5bf2f36aea78329c41552267f8c" id="chapterVideoObjectId"/>
<input type="hidden" id="collectionTime" value="0"/>
<input type="hidden" id="videoRandomCollectTime" value="0"/>
<input type="hidden" id="mid" value="xxx-mid"/>
<input type="hidden" id="chapterIdid" value="909121121"/>
<input type="hidden" id="fcclazzIdQr" value="106478659"/>
<input type="hidden" id="fccourseIdQr" value="246362548"/>
<input type="hidden" id="fccpiQr" value="419533201"/>
<input type="hidden" id="faceBlockEnterVideoQr" value="1"/>
<input type="hidden" id="videoCaptureGetQrStatuse" value="1"/>
<script>
    var url = _HOST_CP2_ + '/qr/produce?uuid=b7079ff7-bac2-484c-bb3c-a190c87ec455&enc=6d32063d34d2da65d6f3f3e5adb45232&clazzid=106478659' + ...
</script>
"""


class FaceQrParseTestCase(unittest.TestCase):
    def test_parse_tree_enc(self):
        self.assertEqual(parse_tree_enc(TREE_HTML), "60f046f94cbf2eb5fc76ba2d0aedd470")
        self.assertIsNone(parse_tree_enc("<html></html>"))

    def test_parse_hidden_both_attribute_orders(self):
        # 服务端渲染时视频字段为空(JS 动态填充), 解析应返回空串
        self.assertEqual(parse_hidden(STUDY_HTML, "videoJobId"), "")
        # value 在 id 之前
        self.assertEqual(parse_hidden(STUDY_HTML, "chapterVideoObjectId"), "d642d5bf2f36aea78329c41552267f8c")
        self.assertEqual(parse_hidden(STUDY_HTML, "mid"), "xxx-mid")
        self.assertEqual(parse_hidden(STUDY_HTML, "notExist"), "")

    def test_has_face_demand(self):
        self.assertTrue(has_face_demand(STUDY_HTML))
        self.assertFalse(has_face_demand(STUDY_HTML.replace('id="videoCaptureGetQrStatuse" value="1"', 'id="videoCaptureGetQrStatuse" value="0"')))
        self.assertFalse(has_face_demand("<html></html>"))

    def test_parse_study_tokens(self):
        tokens = parse_study_tokens(STUDY_HTML)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["produceUuid"], "b7079ff7-bac2-484c-bb3c-a190c87ec455")
        self.assertEqual(tokens["produceEnc"], "6d32063d34d2da65d6f3f3e5adb45232")
        self.assertEqual(tokens["fcclazzIdQr"], "106478659")
        # 服务端渲染的 HTML 中视频相关字段为空, 由调用方补全(对应网页 JS 行为)
        self.assertEqual(tokens["videoJobId"], "")
        self.assertIsNone(parse_study_tokens("<html>无令牌</html>"))

    def test_has_face_markers_course_level_signal(self):
        """课程级人脸抓拍标记: 三种信号任一命中即视为配置(实测对照课三者为空)."""
        # qrStatuse=1
        self.assertTrue(has_face_markers(STUDY_HTML))
        # faceBlock 非空(无 qrStatuse)
        block_only = '<input id="faceBlockEnterVideoQr" value="2"/>'
        self.assertTrue(has_face_markers(block_only))
        # 弹窗模板存在
        self.assertTrue(has_face_markers('<div class="faceCollectQrPopVideo"></div>'))
        # 对照: 未配置课程的页面三者为空
        clean = '<input id="faceBlockEnterVideoQr" value=""/><input id="videoCaptureGetQrStatuse" value=""/>'
        self.assertFalse(has_face_markers(clean))
        self.assertFalse(has_face_markers("<html></html>"))

    def test_fill_tokens_from_job(self):
        tokens = parse_study_tokens(STUDY_HTML)
        filled = fill_tokens_from_job(
            tokens,
            {"jobid": "1599495110005881", "objectid": "d642d5bf", "mid": "m1"},
            chapter_id="909121121",
        )
        self.assertEqual(filled["videoJobId"], "1599495110005881")
        self.assertEqual(filled["chapterVideoObjectId"], "d642d5bf")
        self.assertEqual(filled["mid"], "m1")
        self.assertEqual(filled["chapterIdid"], "909121121")
        # collectionTime 空值补默认
        self.assertEqual(filled["collectionTime"], "0")


if __name__ == "__main__":
    unittest.main()
