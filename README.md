# astrbot_plugin_saucenao_search

AstrBot 的 SauceNAO 搜图插件。发指令，然后把图丢上来，它会反查这张图的出处、作者和原图链接。

## 功能

- 群图直接搜：读取图片字节后 multipart 上传，不依赖图片的公网地址
- 结果按相似度排序，带缩略图、作者、标题、原图链接
- 额度/鉴权/限流都有明确提示，不会只丢一句「失败了」
- 超时机制走后台任务，不阻塞其他消息处理

## 安装

把整个目录放进 AstrBot 的 `data/plugins/` 下，重载插件即可：

```bash
cd AstrBot/data/plugins
git clone https://github.com/wonlie95/astrbot_plugin_saucenao_search.git sauceno_search
```

也可以直接在 AstrBot 的插件管理里用仓库地址安装。

## 配置

在插件配置里填两项：

| 配置项 | 说明 |
| --- | --- |
| `saucenao_api` | SauceNAO 的 API Key，去 https://saucenao.com/user.php 注册后获取 |
| `wait_seconds` | 发指令后等待发图的秒数，默认 30 |

## 用法

```
#&搜图
```

机器人回一句等待提示，接着把图片发上来就行，30 秒内有效。结果会以图文混合的形式返回。

## 注意事项

- SauceNAO 免费账号有额度：每日次数 + 30 秒窗口内的次数限制。超了会提示「额度用完」
- 单张图片限制 10MB
- 只对二次元/插画类图片有效，真人照片基本搜不到

## 更新日志

### v1.0.1

- 修复：原来把 `Image.url` 直接当公网地址传给 API，群里的图片是本地缓存路径，请求必然失败
- 改为读取图片字节后 multipart 上传，支持本地路径 / http(s) / base64 三种来源
- 新增 `header.status` 判断，区分 key 错误、额度用完、图片被拒
- 403 / 429 分别映射为「key 没权限」「被限流」
- 等待发图改为后台计时任务，不再用 `asyncio.sleep` 占住事件
- 结果字段缺失时兜底，避免 KeyError

## License

MIT
