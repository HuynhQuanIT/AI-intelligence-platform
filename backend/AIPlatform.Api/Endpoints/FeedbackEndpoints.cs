using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>Đánh giá 👍/👎 từng câu trả lời (người dùng) và thống kê (admin; ai-service kiểm tra quyền).</summary>
public static class FeedbackEndpoints
{
    public static IEndpointRouteBuilder MapFeedbackEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPut("/api/platform/messages/{messageId:long}/feedback",
            async (long messageId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Put(r, f, $"/messages/{messageId}/feedback"));

        app.MapGet("/api/platform/feedback/summary",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/feedback/summary"));

        return app;
    }
}
