from datetime import datetime, timedelta
from core.models.article import Article
from .article import UpdateArticle,Update_Over
import core.db as db
from core.wx import WxGather
from core.log import logger
from core.task import TaskScheduler
from core.models.feed import Feed
from core.config import cfg,DEBUG
from core.print import print_info,print_success,print_error
from driver.wx import WX_API
from driver.success import Success
wx_db=db.Db(tag="任务调度")
def fetch_all_article():
    print("开始更新")
    wx=WxGather().Model()
    try:
        # 获取公众号列表
        mps=db.DB.get_all_mps()
        for item in mps:
            try:
                wx.get_Articles(item.faker_id,CallBack=UpdateArticle,Mps_id=item.id,Mps_title=item.mp_name, MaxPage=1)
            except Exception as e:
                print(e)
        print(wx.articles) 
    except Exception as e:
        print(e)         
    finally:
        logger.info(f"所有公众号更新完成,共更新{wx.all_count()}条数据")


def test(info:str):
    print("任务测试成功",info)

from core.models.message_task import MessageTask
# from core.queue import TaskQueue
from .webhook import web_hook
interval=int(cfg.get("interval",60)) # 每隔多少秒执行一次
def do_job(mp=None,task:MessageTask=None,isTest=False):
        # TaskQueue.add_task(test,info=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        # print("执行任务", task.mps_id)
        print(f"执行任务 (测试模式: {isTest})")
        all_count=0
        if isTest:
            # 测试模式使用模拟数据
            mock_articles = [{
                "id": "test-article-001",
                "mp_id": mp.id,
                "title": "测试文章标题",
                "pic_url": "https://via.placeholder.com/300x200",
                "url": "https://example.com/test-article",
                "description": "这是一篇测试文章的描述内容，用于测试webhook功能是否正常。",
                "publish_time": (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                "content": "<p>这是测试文章的正文内容。</p>"
            }]
            count = 1
        else:
            wx=WxGather().Model()
            try:
                wx.get_Articles(mp.faker_id,CallBack=UpdateArticle,Mps_id=mp.id,Mps_title=mp.mp_name, MaxPage=1,Over_CallBack=Update_Over,interval=interval)
            except Exception as e:
                print_error(e)
                # raise
            finally:
                count=wx.all_count()
                mock_articles = wx.articles
                all_count+=count

        from jobs.webhook import MessageWebHook
        tms=MessageWebHook(task=task,feed=mp,articles=mock_articles)
        web_hook(tms, is_test=isTest)
        print_success(f"任务({task.id})[{mp.mp_name}]执行成功,{count}成功条数")
        
        # 级联节点：上报任务执行结果到父节点
        from jobs.cascade_sync import cascade_sync_service
        if not isTest and mock_articles:
            import asyncio
            try:
                result_data = [{
                    "mp_id": mp.id,
                    "mp_name": mp.mp_name,
                    "article_count": len(mock_articles) if not isTest else 1,
                    "success_count": count if not isTest else 1,
                    "timestamp": datetime.now().isoformat()
                }]
                # 异步上报，不阻塞主流程
                asyncio.create_task(cascade_sync_service.report_task_result(task.id, result_data))
            except Exception as e:
                print_error(f"上报任务结果失败: {str(e)}")

from core.queue import TaskQueue
def add_job(feeds:list[Feed]=None,task:MessageTask=None,isTest=False):
    if isTest:
        TaskQueue.clear_queue()
    for feed in feeds:
        TaskQueue.add_task(do_job,feed,task,isTest)
        if isTest:
            print(f"测试任务，{feed.mp_name}，加入队列成功")
            reload_job()
            break
        print(f"{feed.mp_name}，加入队列成功")
    print_success(TaskQueue.get_queue_info())
    pass
import json
def get_feeds(task:MessageTask=None):
     mps = json.loads(task.mps_id)
     ids=",".join([item["id"]for item in mps])
     mps=wx_db.get_mps_list(ids)
     if len(mps)==0:
        mps=wx_db.get_all_mps()
     return mps
scheduler=TaskScheduler()
def reload_job():
    print_success("重载任务")
    scheduler.clear_all_jobs()
    TaskQueue.clear_queue()
    start_job()

def run(job_id:str=None,isTest=False):
    from .taskmsg import get_message_task
    tasks=get_message_task(job_id)
    if not tasks:
        print("没有任务")
        return None
    for task in tasks:
            #添加测试任务
            from core.print import print_warning
            print_warning(f"{task.name} 添加到队列运行")
            add_job(get_feeds(task),task,isTest=isTest)
            pass
    return tasks
def start_job(job_id:str=None):
    from .taskmsg import get_message_task
    tasks=get_message_task(job_id)
    if not tasks:
        print("没有任务")
        return
    tag="定时采集"
    for task in tasks:
        cron_exp=task.cron_exp
        if not cron_exp:
            print_error(f"任务[{task.id}]没有设置cron表达式")
            continue
      
        job_id=scheduler.add_cron_job(add_job,cron_expr=cron_exp,args=[get_feeds(task),task],job_id=str(task.id),tag="定时采集")
        print(f"已添加任务: {job_id}")
    scheduler.start()
    print("启动任务")
def start_fix_article():
      #开启自动同步未同步 文章任务
    from jobs.fetch_no_article import start_sync_content
    start_sync_content()
if __name__ == '__main__':
    # do_job()
    # start_all_task()
    pass