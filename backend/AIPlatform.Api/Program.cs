using System.Text;
var builder=WebApplication.CreateBuilder(args);
builder.Services.AddEndpointsApiExplorer();builder.Services.AddSwaggerGen();
builder.Services.AddHttpClient("ai",c=>{c.BaseAddress=new Uri(builder.Configuration["AiService:BaseUrl"]??"http://localhost:8000");c.Timeout=TimeSpan.FromSeconds(90);});
builder.Services.AddCors(o=>o.AddDefaultPolicy(p=>p.WithOrigins("http://localhost:5173").AllowAnyHeader().AllowAnyMethod()));
var app=builder.Build();app.UseCors();if(app.Environment.IsDevelopment()){app.UseSwagger();app.UseSwaggerUI();}
app.MapGet("/health",()=>Results.Ok(new{status="healthy",service="backend"}));
app.MapGet("/api/platform/health",async(IHttpClientFactory f)=>await Get(f,"/health"));
app.MapPost("/api/platform/chat",async(HttpRequest r,IHttpClientFactory f)=>await Post(r,f,"/chat"));
app.MapPost("/api/platform/documents",async(HttpRequest r,IHttpClientFactory f)=>await Post(r,f,"/documents"));
app.MapGet("/api/platform/documents",async(IHttpClientFactory f)=>await Get(f,"/documents"));
app.MapGet("/api/platform/agents",async(IHttpClientFactory f)=>await Get(f,"/agents"));
app.MapGet("/api/platform/metrics",async(IHttpClientFactory f)=>await Get(f,"/metrics"));
app.MapGet("/api/platform/traces",async(IHttpClientFactory f)=>await Get(f,"/traces"));
app.MapPost("/api/platform/evaluate",async(HttpRequest r,IHttpClientFactory f)=>await Post(r,f,"/evaluate"));
app.MapPost("/api/platform/security/scan",async(HttpRequest r,IHttpClientFactory f)=>await Post(r,f,"/security/scan"));
app.MapGet("/api/platform/security/events",async(IHttpClientFactory f)=>await Get(f,"/security/events"));
app.Run();
static async Task<IResult> Get(IHttpClientFactory f,string path){var r=await f.CreateClient("ai").GetAsync(path);return Results.Content(await r.Content.ReadAsStringAsync(),"application/json",statusCode:(int)r.StatusCode);}
static async Task<IResult> Post(HttpRequest req,IHttpClientFactory f,string path){using var sr=new StreamReader(req.Body);var body=await sr.ReadToEndAsync();var r=await f.CreateClient("ai").PostAsync(path,new StringContent(body,Encoding.UTF8,"application/json"));return Results.Content(await r.Content.ReadAsStringAsync(),"application/json",statusCode:(int)r.StatusCode);}
