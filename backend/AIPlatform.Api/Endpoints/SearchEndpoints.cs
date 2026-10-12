using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>Tìm kiếm tài liệu theo từ khóa/ngữ nghĩa. Giữ nguyên query string; ai-service lọc theo quyền xem.</summary>
public static class SearchEndpoints
{
    public static IEndpointRouteBuilder MapSearchEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/platform/search",
            async (HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Get(f, "/search" + r.QueryString.Value));

        return app;
    }
}
