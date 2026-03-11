import uvicorn
from core.config import cfg
from core.print import print_warning, print_info, print_success
import threading
from driver.auth import *
import os
if __name__ == '__main__':
    print("环境变量:")
    for k,v in os.environ.items():
        print(f"{k}={v}")
    if cfg.args.init=="True":
        import init_sys as init
        init.init()
    
    # 启动级联同步服务（如果配置为子节点）
    cascade_service_started = False
    if cfg.get("cascade.enabled", False) and cfg.get("cascade.node_type") == "child":
        try:
            from jobs.cascade_sync import cascade_sync_service
            from jobs.cascade_task_dispatcher import start_child_task_worker
            import asyncio
            
            cascade_sync_service.initialize()
            if cascade_sync_service.sync_enabled:
                # 在后台线程启动同步服务
                def run_sync():
                    asyncio.run(cascade_sync_service.start_periodic_sync())
                
                sync_thread = threading.Thread(target=run_sync, daemon=True)
                sync_thread.start()
                
                # 启动子节点任务拉取器
                poll_interval = cfg.get("cascade.task_poll_interval", 30)
                
                def run_task_worker():
                    asyncio.run(start_child_task_worker(poll_interval=poll_interval))
                
                task_worker_thread = threading.Thread(target=run_task_worker, daemon=True)
                task_worker_thread.start()
                
                cascade_service_started = True
                print_success(f"级联同步服务已启动，任务拉取间隔: {poll_interval}秒")
        except Exception as e:
            print_warning(f"启动级联同步服务失败: {str(e)}")
    else:
        print_info("级联模式未启用或当前节点为父节点")
    
    if not cascade_service_started:
        print_info("启动网关定时调度服务")
        import asyncio
        from jobs.cascade_task_dispatcher import cascade_schedule_service
        cascade_schedule_service.start()

    if  cfg.args.job =="True" and cfg.get("server.enable_job",False):
        from jobs import start_job
        threading.Thread(target=start_job,daemon=False).start()
        print_success("已开启定时任务")
    else:
        print_warning("未开启定时任务")
    if cfg.get("gather.content_auto_check",False):
        from jobs import start_fix_article
        start_fix_article()
        print_success("已开启自动修正文章任务")
    else:
        print_warning("未开启自动修正文章任务")
    print("启动服务器")
    AutoReload=cfg.get("server.auto_reload",False)
    thread=cfg.get("server.threads",1)
    reload_dirs = ["apis", "core", "driver", "jobs", "schemas", "tools", "views", "web_ui"]
    uvicorn.run("web:app", host="0.0.0.0", port=int(cfg.get("port",8001)),
            reload=AutoReload,
            reload_dirs=reload_dirs,
            reload_excludes=['static','data'],
            workers=thread,
            )
    pass
