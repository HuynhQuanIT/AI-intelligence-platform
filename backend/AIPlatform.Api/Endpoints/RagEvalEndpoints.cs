using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>Đo chất lượng truy xuất RAG trên tài liệu thật (admin; ai-service kiểm tra quyền).</summary>
public static class RagEvalEndpoints
{
    public static IEndpointRouteBuilder MapRagEvalEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/platform/rag-eval",
            async (HttpRequest r, IHttpClientFactory f) => await AiProxy.Post(r, f, "/rag-eval"));

        return app;
    }
}
