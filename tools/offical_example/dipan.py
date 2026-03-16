from ./../../rerobot-study/ugv/jetson/base_ctrl import BaseController
import json

base = BaseController('/dev/ttyCH341USB0', 115200)

# 使用无限循环来不断监听串口数据
while True:
    try:
        # 从串口读取一行数据，解码成 'utf-8' 格式的字符串，并尝试将其转换为 JSON 对象
        data_recv_buffer = json.loads(base.rl.readline().decode('utf-8'))
        # 检查解析出的数据中是否包含 'T' 键
        if 'T' in data_recv_buffer:
            # 如果 'T' 的值为 1001，则打印接收到的数据，并跳出循环
            if data_recv_buffer['T'] == 1001:
                print(data_recv_buffer)
                break
    # 如果在读取或处理数据时发生异常，则忽略该异常并继续监听下一行数据
    except:
        pass