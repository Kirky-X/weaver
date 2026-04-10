## 1. NewsNow Parser 更新

- [x] 1.1 更新 `NewsNowParser.API_BASE_URL` 常量为 `https://www.newsnow.world/api/s?id=`
- [x] 1.2 验证全局无其他 `newsnow.net.cn` 引用

## 2. 测试脚本参数化

- [x] 2.1 添加 `--source-id` 命令行参数，默认值 `36kr`
- [x] 2.2 修改 `fetch_newsnow_data` 函数，使用参数构建完整 API URL
- [x] 2.3 更新帮助文档和示例

## 3. 验证

- [x] 3.1 运行测试脚本验证 36kr 源
- [x] 3.2 验证帮助文本显示新参数