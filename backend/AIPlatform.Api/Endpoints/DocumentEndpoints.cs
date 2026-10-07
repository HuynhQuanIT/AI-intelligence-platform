using System.Net.Http.Headers;
using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class DocumentEndpoints
{
    private const long MaxUploadBytes = 11 * 1024 * 1024; // 10 MB file + phần đệm multipart

    public static IEndpointRouteBuilder MapDocumentEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/platform/documents");

        group.MapPost("",
            async (HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, "/documents"));

        group.MapPost("/upload", Upload);

        group.MapGet("",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/documents"));

        group.MapGet("/{documentId}",
            async (string documentId, IHttpClientFactory f) =>
                await AiProxy.Get(f, $"/documents/{Uri.EscapeDataString(documentId)}"));

        group.MapDelete("/{documentId}",
            async (string documentId, IHttpClientFactory f) =>
                await AiProxy.Delete(f, $"/documents/{Uri.EscapeDataString(documentId)}"));

        group.MapGet("/{documentId}/file", Download);

        return app;
    }

    // Chuyển nguyên multipart sang ai-service, không parse ở gateway.
    private static async Task<IResult> Upload(HttpRequest r, IHttpClientFactory f)
    {
        if (!r.HasFormContentType || string.IsNullOrEmpty(r.ContentType))
        {
            return Results.Json(
                new { detail = "Expected multipart/form-data." },
                statusCode: StatusCodes.Status415UnsupportedMediaType);
        }

        if (r.ContentLength is > MaxUploadBytes)
        {
            return Results.Json(
                new { detail = "File vượt quá 10 MB." },
                statusCode: StatusCodes.Status413PayloadTooLarge);
        }

        using var buffer = new MemoryStream();
        await r.Body.CopyToAsync(buffer);
        if (buffer.Length > MaxUploadBytes)
        {
            return Results.Json(
                new { detail = "File vượt quá 10 MB." },
                statusCode: StatusCodes.Status413PayloadTooLarge);
        }
        buffer.Position = 0;

        using var content = new StreamContent(buffer);
        content.Headers.ContentType = MediaTypeHeaderValue.Parse(r.ContentType);

        return await AiProxy.Relay(await f.AiClient().PostAsync("/documents/upload", content));
    }

    private static async Task<IResult> Download(
        string documentId, HttpContext ctx, IHttpClientFactory f)
    {
        var response = await f.AiClient().GetAsync(
            $"/documents/{Uri.EscapeDataString(documentId)}/file");

        if (!response.IsSuccessStatusCode)
        {
            return await AiProxy.Relay(response);
        }

        var name = "document";
        if (response.Headers.TryGetValues("X-Document-Filename", out var values))
        {
            name = Uri.UnescapeDataString(values.First());
        }

        var contentType = response.Content.Headers.ContentType?.ToString()
            ?? "application/octet-stream";

        ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";

        return Results.File(
            await response.Content.ReadAsByteArrayAsync(),
            contentType,
            name);
    }
}
