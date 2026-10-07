using System.Text;
using System.Text.Json;
using AIPlatform.Api.Models;
using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class ChatEndpoints
{
    public static IEndpointRouteBuilder MapChatEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/platform/chat",
            async (ChatRequest body, IHttpClientFactory f) =>
            {
                var json = JsonSerializer.Serialize(body);

                return await AiProxy.Relay(await f.AiClient().PostAsync(
                    "/chat",
                    new StringContent(json, Encoding.UTF8, "application/json")));
            })
            .Accepts<ChatRequest>("application/json");

        app.MapPost("/api/platform/chat/stream", StreamChat)
            .Accepts<ChatRequest>("application/json");

        return app;
    }

    // Chuyển tiếp luồng SSE từ ai-service tới trình duyệt từng đoạn một.
    private static async Task StreamChat(ChatRequest body, HttpContext ctx, IHttpClientFactory f)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "/chat/stream")
        {
            Content = new StringContent(
                JsonSerializer.Serialize(body), Encoding.UTF8, "application/json")
        };

        // ResponseHeadersRead: nhận header ngay, rồi chuyển tiếp từng đoạn khi ai-service gửi.
        using var response = await f.AiClient().SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, ctx.RequestAborted);

        ctx.Response.StatusCode = (int)response.StatusCode;
        ctx.Response.ContentType = response.IsSuccessStatusCode
            ? "text/event-stream"
            : "application/json";
        ctx.Response.Headers["Cache-Control"] = "no-cache";
        ctx.Response.Headers["X-Accel-Buffering"] = "no";

        try
        {
            await using var stream = await response.Content.ReadAsStreamAsync(ctx.RequestAborted);
            var buffer = new byte[4096];
            int read;
            while ((read = await stream.ReadAsync(buffer.AsMemory(), ctx.RequestAborted)) > 0)
            {
                await ctx.Response.Body.WriteAsync(buffer.AsMemory(0, read), ctx.RequestAborted);
                await ctx.Response.Body.FlushAsync(ctx.RequestAborted);
            }
        }
        catch (OperationCanceledException)
        {
            // Trình duyệt đóng kết nối giữa chừng: không phải lỗi.
        }
    }
}
