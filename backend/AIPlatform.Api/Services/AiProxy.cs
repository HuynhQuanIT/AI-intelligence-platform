using System.Text;

namespace AIPlatform.Api.Services;

/// <summary>
/// Chuyển tiếp request của gateway sang ai-service và trả nguyên trạng thái, nội dung JSON.
/// </summary>
public static class AiProxy
{
    public const string ClientName = "ai";

    public static HttpClient AiClient(this IHttpClientFactory factory) =>
        factory.CreateClient(ClientName);

    /// <summary>Trả lại phản hồi của ai-service (cùng mã trạng thái) dưới dạng JSON.</summary>
    public static async Task<IResult> Relay(HttpResponseMessage response) =>
        Results.Content(
            await response.Content.ReadAsStringAsync(),
            "application/json",
            statusCode: (int)response.StatusCode);

    public static async Task<IResult> Get(IHttpClientFactory f, string path) =>
        await Relay(await f.AiClient().GetAsync(path));

    public static async Task<IResult> Delete(IHttpClientFactory f, string path) =>
        await Relay(await f.AiClient().DeleteAsync(path));

    /// <summary>POST không có nội dung.</summary>
    public static async Task<IResult> PostEmpty(IHttpClientFactory f, string path) =>
        await Relay(await f.AiClient().PostAsync(path, null));

    /// <summary>POST nguyên văn body JSON của request hiện tại.</summary>
    public static async Task<IResult> Post(HttpRequest req, IHttpClientFactory f, string path)
    {
        using var reader = new StreamReader(req.Body);
        var body = await reader.ReadToEndAsync();

        return await Relay(await f.AiClient().PostAsync(
            path,
            new StringContent(body, Encoding.UTF8, "application/json")));
    }
}
