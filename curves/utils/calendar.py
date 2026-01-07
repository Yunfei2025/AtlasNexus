# -*- coding: utf-8 -*-
"""
Created on Wed Aug 10 13:59:10 2022

@author: 马云飞
"""

import pandas as pd
import requests
import json
import numpy as np
import re
import warnings
from dateutil.relativedelta import relativedelta

warnings.filterwarnings("ignore")

def getScheduleDays(day,curve_type,standard=True):
    ends = {}
    if standard:
        if curve_type == 'r7d':
            ends['7D'] = day + relativedelta(days=7)
            ends['1M'] = day + relativedelta(months=1)
        #if curve_type == 's3m':
        ends['3M'] = day + relativedelta(months=3)
        ends['6M'] = day + relativedelta(months=6)
        ends['9M'] = day + relativedelta(months=9)
        for i in range(10):
            ends[str(i + 1) + 'Y'] = day + relativedelta(years=i + 1)
        # else:
        #     pass
        days = pd.Series()
        for k in ends.keys():
            days.loc[k] = (ends[k] - day).days
    else:    
        nsts = []
        if not standard:
            nst = day
            if curve_type == 'r7d':
                nsts.append(day+ relativedelta(days=7))
                nsts.append(day + relativedelta(months=1))
            for i in range(10*4):
                nst = nst + relativedelta(months=3)
                nsts.append(nst)
        days = [ (d - day).days for d in nsts ]        
        days = pd.Series(days)
    return days

def getCalendar(year):
    df=pd.DataFrame()
    # 获取法定节假日
    up1='https://sp1.baidu.com/8aQDcjqpAAV3otqbppnN2DJv/api.php?tn=wisetpl&format=json&resource_id=39043&query='
    up2='月&t=1642579711570&cb=op_aladdin_callback1642579711570'
    # 2022年接口已经改为按月获取数据，因此循环12个月获取每月数据
    for i in range(1,13):
        url="".join([up1,str(year),"年",str(i),up2])
        r=requests.get(url)
        rtxt=re.split("[()]", r.text)[1]
        r_json=json.loads(rtxt)
        each_d1=pd.DataFrame(r_json['data'])
        each_d2=pd.DataFrame(each_d1['almanac'][0])
        ## 筛选当月数据，数据中year\month\day是公立日期，数据会返回3个月的数据
        each_d3=each_d2[each_d2['month']==str(i)]
        # ## 由于12月的数据没有status字段（可能是下一年一月放假规定没出来，所以这里进行特殊处理)--结论应该是某些月份没有节假日就没有status字段，所以后面专门针对status进行处理
        # if i==11:
        #     each_d3=each_d2[each_d2['month']>=str(i)]
        # else:
        #     each_d3=each_d2[each_d2['month']==str(i)]
        ## 组合真的日期，并标记节假日情况
        each_d3['公历日期']=pd.to_datetime(each_d3['year']+"/"+each_d3['month']+"/"+each_d3['day'])
        each_d3['Weekday']=each_d3['公历日期'].dt.dayofweek+1
        ## 标记是否节假日(即当天是否是法定放假)，其中status中的1表示放假，2表示上班，注意需要处理有没有status列的情况
        ## 有status的情况
        if "status" in each_d3.columns:
            each_d3['status'].fillna(0,inplace=True)
            each_d3['status']=each_d3['status'].astype('int',errors='ignore')
            ## 按周几把周末标记成1，周一至周五标记成0，然后通过标记和status的值相加，结果为1和2的就是假期
            judge=np.where(each_d3['Weekday']<6,0,1)+each_d3['status']
            each_d3['Holiday']=np.where((judge==1) | (judge==2),True,False)
            df=df.append(each_d3)
            # each_d3.to_csv("百度日历.csv",index=False)
        ## 没有status的情况，直接按周末为节假日
        else:
            each_d3['Holiday']=np.where(each_d3['Weekday']>=6,True,False)
            df=df.append(each_d3)
    # 重命名列
    df.rename(columns={'animal':'生肖','avoid':'忌','cnDay':'中文星期','day':'日',
                       'gzDate':'干支日','gzMonth':'干支月','gzYear':'干支年',
                       'isBigMonth':'是否为阴历大月','lDate':'中文阴历日','lMonth':'中文阴历月',
                       'lunarDate':'数字阴历日','lunarMonth':'数字阴历月','lunarYear':'数字阴历年',
                       'month':'月','oDate':'阳历当天0点','suit':'宜','term':'节气节日',
                       'type':'各种与节日有关的类型','value':'各种日','year':'年','desc':'一种节日',
                       'status':'1休假2上班'},
              inplace=True)
    df.set_index('公历日期',inplace=True)
    
    adjholidays = []
    adjworkdays = []
    if year == 2023:        
        for m in [1,4,5,6,9,10]:
            if m == 1:
                hlist = [1,2,21,22,23,24,25,26,27] 
                wlist = [28,29]
            elif m == 4:    
                hlist = [3,4,5,29,30] 
                wlist = [1,2,9,22]
            elif m == 5:    
                hlist = [1,2,3] 
                wlist = [6]
            elif m == 6:    
                hlist = [22,23,24] 
                wlist = [25]
            elif m == 9:    
                hlist = [29,30] 
                wlist = [23]
            elif m == 10:    
                hlist = [1,2,3,4,5,6,7] 
                wlist = [8]          
            adjholidays.extend([pd.Timestamp(year,m,d) for d in hlist])
            adjworkdays.extend([pd.Timestamp(year,m,d) for d in wlist])
    elif year == 2024:
        for m in [1,2,4,5,6,9,10]:
            if m == 1:
                hlist = [1] 
                wlist = []
            elif m == 2:    
                hlist = [10,11,12,13,14,15,17] 
                wlist = [18]
            elif m == 4:    
                hlist = [4,5,29,30] 
                wlist = [7,27]
            elif m == 5:    
                hlist = [1] 
                wlist = [4]
            elif m == 6:    
                hlist = [10] 
                wlist = []
            elif m == 9:    
                hlist = [17,18] 
                wlist = [14,21,28]
            elif m == 10:    
                hlist = [1,2,3,4,5,6,7] 
                wlist = [8]          
            adjholidays.extend([pd.Timestamp(year,m,d) for d in hlist])
            adjworkdays.extend([pd.Timestamp(year,m,d) for d in wlist])
            
    df.loc[adjholidays,'Holiday'] = True
    df.loc[adjworkdays,'Holiday'] = False
    return df['Holiday']

def getNextTradingDate(Cal,datelist):
    hd = Cal[Cal]
    adjlist = []
    for i,d in enumerate(datelist):
        while (d in hd.index):
            d += relativedelta(days=1)
        adjlist.append(d)
    return adjlist
